from transformers import pipeline
import os
import sys

class MaleFemaleClassifier:
    def __init__(self, model_name="norwoodsystems/norwood-maleVSfemale"):
        self.model_name = model_name
        self.pipe = pipeline("audio-classification", model=self.model_name)

    def classify(self, file_path):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        result = self.pipe(file_path)[0]
        return result["label"]

audio_file = sys.argv[1]
classifier = MaleFemaleClassifier()
label = classifier.classify(audio_file)
print(f"{audio_file} → {label}")

