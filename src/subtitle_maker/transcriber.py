import torch
import os
import uuid
import ffmpeg
import logging
from transformers import AutoModelForCausalLM, AutoTokenizer
from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner
from qwen_asr.core.transformers_backend.processing_qwen3_asr import Qwen3ASRProcessor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SubtitleGenerator:
    def __init__(self, model_path="Qwen/Qwen3-ASR-0.6B", aligner_path="Qwen/Qwen3-ForcedAligner-0.6B", device="mps", lazy_load=False):
        self.device = device
        self.dtype = torch.float16 if device == "mps" else torch.bfloat16
        self.model_path = model_path
        self.aligner_path = aligner_path
        self.model = None
        
        logger.info(f"Initializing SubtitleGenerator on {device} (Lazy Load: {lazy_load})")
        
        if not lazy_load:
            self.load_model()

    def load_model(self):
        if self.model is not None:
            return

        logger.info(f"Loading ASR models on {self.device} with {self.dtype}...")
        try:
            self.model = Qwen3ASRModel.from_pretrained(
                self.model_path,
                dtype=self.dtype,
                device_map=self.device,
                forced_aligner=self.aligner_path,
                forced_aligner_kwargs=dict(
                    dtype=self.dtype,
                    device_map=self.device,
                ),
            )
            logger.info("ASR Models loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load models: {e}")
            raise

    def unload_model(self):
        if self.model is not None:
            logger.info("Unloading ASR model to free memory...")
            del self.model
            self.model = None
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            elif torch.cuda.is_available():
                torch.cuda.empty_cache()
            import gc
            gc.collect()
            logger.info("ASR Model unloaded.")

    def preprocess_audio(self, input_path):
        """
        Convert audio to 16kHz mono wav.
        Returns the path to the processed audio.
        """
        session_id = str(uuid.uuid4())
        output_path = f"temp_audio_{session_id}.wav"
        try:
            logger.info(f"Preprocessing audio: {input_path}")
            (
                ffmpeg
                .input(input_path)
                .output(output_path, ac=1, ar=16000, loglevel="quiet")
                .overwrite_output()
                .run()
            )
            return output_path
        except ffmpeg.Error as e:
            logger.error(f"FFmpeg error: {e}")
            raise

    def transcribe(self, audio_path, language=None):
        """
        Transcribe audio and return results with timestamps.
        """
        processed_audio = self.preprocess_audio(audio_path)
        logger.info("Starting transcription...")
        
        try:
            # specific logic for Qwen3-ASR inference
            # result is a list of objects with text, language, and time_stamps
            if language and language.lower() == "auto":
                language = None
                
            results = self.model.transcribe(
                audio=processed_audio,
                language=language,
                return_time_stamps=True
            )
            
            return results
        finally:
             if os.path.exists(processed_audio):
                 os.remove(processed_audio)

    def transcribe_iter(self, audio_path, language=None, chunk_size=30, preprocessed=False):
        """
        Transcribe audio in chunks and YIELD results.
        chunk_size: seconds
        """
        processed_audio = audio_path if preprocessed else self.preprocess_audio(audio_path)
        cleanup_processed = not preprocessed
        # Session ID is embedded in the filename
        # We need it for chunk naming or just use uuid again? 
        # Actually easier to just generate a random ID for chunks
        session_id = str(uuid.uuid4())
        
        # Get duration
        try:
             probe = ffmpeg.probe(processed_audio)
             duration = float(probe['format']['duration'])
        except Exception:
             duration = 3600 # Fallback 1 hour? Or just loop until failure
             
        logger.info(f"Starting chunked transcription (duration: {duration}s, chunk: {chunk_size}s)...")
        
        import math
        chunks = math.ceil(duration / chunk_size)
        
        try:
            for i in range(chunks):
                start_time = i * chunk_size
                
                # Create a temp chunk file
                chunk_path = f"temp_chunk_{session_id}_{i}.wav"
                
                try:
                    (
                        ffmpeg
                        .input(processed_audio, ss=start_time, t=chunk_size)
                        .output(chunk_path, ac=1, ar=16000, loglevel="quiet")
                        .overwrite_output()
                        .run()
                    )
                    
                    # Transcribe chunk
                    if language and language.lower() == "auto":
                        lang_arg = None
                    else:
                        lang_arg = language

                    chunk_results = self.model.transcribe(
                        audio=chunk_path,
                        language=lang_arg,
                        return_time_stamps=True
                    )
                    
                    # Adjust timestamps and convert to DICT immediately to free memory
                    chunk_data = []
                    path_offset = start_time
                    
                    for res in chunk_results:
                        # 'res' is an object with .text, .time_stamps (list of objects)
                        res_dict = {
                            "text": res.text,
                            "time_stamps": []
                        }
                        
                        if hasattr(res, 'time_stamps') and res.time_stamps:
                            for ts in res.time_stamps:
                                # Convert to pure float/str dict
                                ts_dict = {
                                    "text": ts.text,
                                    "start_time": float(ts.start_time + path_offset),
                                    "end_time": float(ts.end_time + path_offset)
                                }
                                res_dict["time_stamps"].append(ts_dict)
                                
                        chunk_data.append(res_dict)
                    
                    # Delete original heavy objects immediately
                    del chunk_results
                    
                    logger.info(f"Yielding chunk {i} results (converted to local dicts)...")
                    yield chunk_data
                    
                except Exception as e:
                    logger.error(f"Error processing chunk {i}: {e}")
                    continue
                finally:
                    if os.path.exists(chunk_path):
                        os.remove(chunk_path)
                    
                    # Explicit cleanup to prevent memory buildup
                    import gc
                    if torch.backends.mps.is_available():
                        torch.mps.empty_cache()
                    gc.collect()
        finally:
            # Clean up the main processed audio if we created it
            if cleanup_processed and os.path.exists(processed_audio):
                os.remove(processed_audio)

    def generate_subtitles(self, results, max_len=40):
        """
        Generate structured subtitles from transcription results.
        Returns a list of dicts: {'start': float, 'end': float, 'text': str}
        Input 'results' should be a list of DICTS now.
        """
        subtitles = []
        
        for res in results:
            # Handle both dict (new) and object (old/direct) just in case, but prioritize dict
            time_stamps = res.get("time_stamps") if isinstance(res, dict) else res.time_stamps
            full_text = res.get("text") if isinstance(res, dict) else res.text
            
            if not time_stamps:
                continue
            
            text_cursor = 0
            
            current_line = []
            current_start = None
            
            for i, ts in enumerate(time_stamps):
                # ts is dict
                token = ts["text"] if isinstance(ts, dict) else ts.text
                start = ts["start_time"] if isinstance(ts, dict) else ts.start_time
                end = ts["end_time"] if isinstance(ts, dict) else ts.end_time
                
                # Find token in full_text to get the "gap" (punctuation/spaces)
                match_index = full_text.find(token, text_cursor)
                
                gap = ""
                if match_index != -1:
                    gap = full_text[text_cursor:match_index]
                    text_cursor = match_index + len(token)
                
                if current_start is None:
                    current_start = start
                
                # Append the gap
                current_line.append(gap)
                
                # Check splitting conditions
                line_text_so_far = "".join(current_line)
                
                is_pause = False
                if i < len(time_stamps) - 1:
                    next_ts = time_stamps[i+1]
                    next_start = next_ts["start_time"] if isinstance(next_ts, dict) else next_ts.start_time
                    if next_start - end > 0.5: # 0.5s pause
                        is_pause = True
                else:
                    is_pause = True 
                
                has_stop_punct = any(p in gap for p in ".?!。？！")
                
                should_split = False
                if len(line_text_so_far) + len(token) > max_len:
                    should_split = True
                elif is_pause:
                    should_split = True
                elif has_stop_punct:
                    should_split = True
                    
                if should_split and current_line:
                    actual_end = end
                    if i < len(time_stamps) - 1:
                        next_ts = time_stamps[i+1]
                        next_token_start = next_ts["start_time"] if isinstance(next_ts, dict) else next_ts.start_time
                        if actual_end > next_token_start:
                            actual_end = max(current_start, next_token_start - 0.01)

                    final_line_text = "".join(current_line).strip()
                    if final_line_text:
                        subtitles.append({
                            "start": current_start,
                            "end": actual_end,
                            "text": final_line_text
                        })
                    
                    current_line = []
                    current_start = None
                
                if current_start is None:
                    current_start = start
                current_line.append(token)
            
            # Handle remaining buffer
            if current_line:
                trailing = full_text[text_cursor:]
                current_line.append(trailing)
                
                last_ts = time_stamps[-1]
                actual_end = last_ts["end_time"] if isinstance(last_ts, dict) else last_ts.end_time
                
                final_line_text = "".join(current_line).strip()
                if final_line_text:
                     subtitles.append({
                        "start": current_start,
                        "end": actual_end,
                        "text": final_line_text
                    })

        return subtitles

    # Methods moved to module level functions

def seconds_to_srt_time(seconds):
    millis = int((seconds % 1) * 1000)
    seconds = int(seconds)
    minutes = seconds // 60
    hours = minutes // 60
    minutes = minutes % 60
    seconds = seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"

def format_srt(subtitles):
    """
    Convert structured subtitles to SRT string.
    """
    srt_content = []
    for i, sub in enumerate(subtitles):
        start_str = seconds_to_srt_time(sub['start'])
        end_str = seconds_to_srt_time(sub['end'])
        srt_content.append(f"{i+1}\n{start_str} --> {end_str}\n{sub['text']}\n")
        
    return "\n".join(srt_content)

def merge_subtitles(original, translated, order="orig_trans"):
    """
    Merge original and translated subtitles into a single list.
    order: 'orig_trans' (Original then Translation) or 'trans_orig' (Translation then Original)
    """
    merged = []
    # Zip safely, though lengths should be equal from translator
    for o, t in zip(original, translated):
        new_sub = o.copy()
        o_text = o['text']
        t_text = t['text']
        
        if order == "orig_trans":
            new_sub['text'] = f"{o_text}\n{t_text}"
        elif order == "trans_orig":
            new_sub['text'] = f"{t_text}\n{o_text}"
        
        merged.append(new_sub)
    return merged

def parse_srt(srt_content: str):
    """
    Parse an SRT string into a list of subtitles.
    Returns: [{'start': float, 'end': float, 'text': str}, ...]
    """
    subtitles = []
    blocks = srt_content.strip().split('\n\n')
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
            
        # Line 1: Index (skip)
        
        # Line 2: Timecode
        timecode = lines[1]
        if '-->' not in timecode:
            continue
            
        start_str, end_str = timecode.split('-->')
        
        # Line 3+: Text
        text = " ".join(lines[2:])
        
        try:
            start = _srt_time_to_seconds(start_str.strip())
            end = _srt_time_to_seconds(end_str.strip())
            subtitles.append({
                'start': start,
                'end': end,
                'text': text
            })
        except Exception:
            continue
            
    return subtitles

def _srt_time_to_seconds(time_str):
    # 00:00:00,000
    time_str = time_str.replace(',', '.')
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds
