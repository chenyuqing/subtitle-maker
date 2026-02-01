import argparse
import logging
from .transcriber import SubtitleGenerator
from .translator import Translator
import os

def main():
    parser = argparse.ArgumentParser(description="Generate SRT subtitles from audio/video using Qwen3-ASR")
    parser.add_argument("input_path", help="Path to input audio or video file")
    parser.add_argument("--output_srt", help="Output SRT file path (optional, defaults to input name)")
    parser.add_argument("--max_width", type=int, default=40, help="Max characters per subtitle line")
    parser.add_argument("--language", help="Force language (e.g., 'Chinese', 'English')")
    parser.add_argument("--device", default="mps", help="Device to use (mps, cuda, cpu)")
    parser.add_argument("--model_path", default="./models/Qwen3-ASR-0.6B", help="Path to ASR model (local or HF hub)")
    parser.add_argument("--aligner_path", default="./models/Qwen3-ForcedAligner-0.6B", help="Path to Aligner model (local or HF hub)")
    parser.add_argument("--translate_to", help="Target language for translation (e.g. 'English')")
    parser.add_argument("--api_key", help="DeepSeek API Key")

    args = parser.parse_args()

    # Determine output path if not provided
    if not args.output_srt:
        base, _ = os.path.splitext(args.input_path)
        args.output_srt = f"{base}.srt"

    print(f"Input: {args.input_path}")
    print(f"Output: {args.output_srt}")
    print(f"Device: {args.device}")

    try:
        generator = SubtitleGenerator(
            model_path=args.model_path,
            aligner_path=args.aligner_path,
            device=args.device
        )
        print("Model loaded. Transcribing...")
        
        results = generator.transcribe(args.input_path, language=args.language)
        print("Transcription complete. Formatting subtitles...")
        
        # New API usage
        subtitles = generator.generate_subtitles(results, max_len=args.max_width)
        srt_content = generator.format_srt(subtitles)
        
        with open(args.output_srt, "w", encoding="utf-8") as f:
            f.write(srt_content)
            
        print(f"Done! Original SRT saved to {args.output_srt}")
        
        # Translation Logic
        if args.translate_to:
            print(f"Translating to {args.translate_to} using DeepSeek...")
            translator = Translator(api_key=args.api_key)
            
            # Extract texts
            original_texts = [sub['text'] for sub in subtitles]
            translated_texts = translator.translate_batch(original_texts, target_lang=args.translate_to)
            
            # Create translated subtitles
            translated_subtitles = []
            for sub, trans_text in zip(subtitles, translated_texts):
                new_sub = sub.copy()
                new_sub['text'] = trans_text
                translated_subtitles.append(new_sub)
                
            # Generate SRT
            trans_srt_content = generator.format_srt(translated_subtitles)
            
            # Save to separate file
            base, ext = os.path.splitext(args.output_srt)
            trans_output_path = f"{base}.{args.translate_to}{ext}"
            
            with open(trans_output_path, "w", encoding="utf-8") as f:
                f.write(trans_srt_content)
                
            print(f"Done! Translated SRT saved to {trans_output_path}")

    except Exception as e:
        print(f"Error: {e}")
        logging.error(e, exc_info=True)

if __name__ == "__main__":
    main()
