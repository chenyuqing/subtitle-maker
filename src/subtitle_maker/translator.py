import os
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

class Translator:
    def __init__(self, api_key=None, base_url="https://api.deepseek.com", model="deepseek-chat"):
        self.base_url = base_url
        self.model = model

        final_api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not final_api_key:
            raise ValueError("DeepSeek API Key is required. Pass it via --api_key or set DEEPSEEK_API_KEY env var.")

        self.client = OpenAI(
            api_key=final_api_key,
            base_url=base_url
        )

    def _build_prompt(self, subtitles, target_lang):
        input_text = "\n".join([f"{i+1}. {text}" for i, text in enumerate(subtitles)])
        return f"""Translate the following lines into {target_lang}.
Maintain the tone and meaning. Output format must correspond line by line.
Return ONLY the translated lines, numbered as in the input.

Input:
{input_text}
"""

    def _parse_translated_lines(self, content: str, expected_len: int):
        translated_lines = []
        for line in content.split('\n'):
            if "." in line:
                parts = line.split(".", 1)
                if parts[0].strip().isdigit():
                    translated_lines.append(parts[1].strip())
                    continue
            if line.strip():
                translated_lines.append(line.strip())

        if len(translated_lines) != expected_len:
            logger.warning("Translation count mismatch: %s vs %s", expected_len, len(translated_lines))
            if len(translated_lines) < expected_len:
                translated_lines.extend([""] * (expected_len - len(translated_lines)))
            else:
                translated_lines = translated_lines[:expected_len]
        return translated_lines

    def translate_batch(self, subtitles, target_lang="Chinese", system_prompt=None, chunk_size=30):
        if not subtitles:
            return []

        all_translated = []
        total = len(subtitles)
        
        for i in range(0, total, chunk_size):
            batch = subtitles[i:i+chunk_size]
            current_batch_texts = [sub if isinstance(sub, str) else sub['text'] for sub in batch] # Handle minimal strings or dicts
            
            logger.info(f"Translating batch {i//chunk_size + 1}/{(total + chunk_size - 1)//chunk_size} ({len(batch)} lines)...")
            
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt if system_prompt and system_prompt.strip() else "You are a professional subtitle translator."},
                        {"role": "user", "content": self._build_prompt(current_batch_texts, target_lang)}
                    ],
                    stream=False
                )
                content = response.choices[0].message.content.strip()
                parsed = self._parse_translated_lines(content, len(batch))
                all_translated.extend(parsed)
                
            except Exception as e:
                logger.error(f"Batch translation failed: {e}")
                # Fallback for this batch
                all_translated.extend([f"[Error] {t}" for t in current_batch_texts])
                
        return all_translated
