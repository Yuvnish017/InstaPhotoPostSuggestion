from transformers import VisionEncoderDecoderModel, ViTImageProcessor, AutoTokenizer
import torch
import google.generativeai as genai
from logger import Logger
import os
import datetime
from datetime import datetime
import traceback
from utils import pil_from_bytes

LOGGER = Logger(log_file_name="caption_generator.log")

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
genai_model = genai.GenerativeModel("gemini-1.5-flash")

caption_gen_model = VisionEncoderDecoderModel.from_pretrained("nlpconnect/vit-gpt2-image-captioning")
caption_processor = ViTImageProcessor.from_pretrained("nlpconnect/vit-gpt2-image-captioning")
caption_tokenizer = AutoTokenizer.from_pretrained("nlpconnect/vit-gpt2-image-captioning")

CAPTION_STYLES = {
    "vibrant": "A vibrant and lively photo with rich colors and dynamic composition.",
    "moody": "A moody and atmospheric photo with deep shadows and dramatic lighting.",
    "cozy": "A cozy and warm photo with soft lighting and inviting tones.",
    "neutral": "A well-balanced photo with neutral tones and good composition."
}


def generate_vision_caption(image_bytes):
    image = pil_from_bytes(image_bytes)
    image = image.resize((224, 224))  # ViT-GPT2 expects 224x224 input
    inputs = caption_processor(images=image, return_tensors="pt").pixel_values

    with torch.no_grad():
        outputs = caption_gen_model.generate(inputs, max_length=20, num_beams=4)

    caption = caption_tokenizer.decode(outputs[0], skip_special_tokens=True)
    return caption.strip()


def infer_mood(brightness, warmth, composition, harmony):
    """Simple heuristic mood inference based on combined metrics."""
    if brightness > 0.7 and warmth > 0.6 and harmony > 0.6:
        return "vibrant"
    elif brightness < 0.4 and composition > 0.7:
        return "moody"
    elif warmth > 0.7 and harmony < 0.5:
        return "cozy"
    else:
        return "neutral"
    

def build_prompt(vision_caption, mood, style):
    """Construct a prompt for caption generation based on vision model output and inferred mood."""
    style_data = CAPTION_STYLES.get(style, CAPTION_STYLES["neutral"])
    prompt = f"""
    Generate 3 Instagram photography captions.

    Scene: 
    {vision_caption}

    Mood: 
    {mood}

    Style:
    {style}

    Tone: 
    {style_data}

    Rules:
    - Keep it concise (1-2 sentences).
    - Give 3 relevant hashtags based on the scene and mood.
    - aesthetic photography page
    - avoid generic captions like "beautiful photo" or "lovely shot".
    - Use engaging language that encourages interaction (likes/comments).
    - Generate caption that tells a story or evokes emotion related to the scene and mood.

    Return only captions.
    """
    return prompt.strip()

def get_llm_response(prompt):
    """Call Gemini 1.5 Flash with the constructed prompt to get caption suggestions."""
    try:
        response = genai_model.generate_content(
            model="gemini-1.5-flash",
            content=prompt,
            max_output_tokens=150
        )
        return response.text.strip()
    except Exception as err:
        LOGGER.error(f"LLM generation failed: {err}")
        LOGGER.error(traceback.format_exc())
        return "Caption generation failed."


def gen_caption_suggestion(filename, analysis):
    """Build a short human-readable caption and hashtag suggestion."""
    parts = []
    if analysis["face_count"] > 0:
        parts.append("portrait")
    else:
        parts.append("shot")

    # dom = analysis["dominant_color"]
    # r, g, b = dom
    # if r > 180 and g > 120:
    #     parts.append("warm tones")
    # elif b > 140:
    #     parts.append("cool tones")

    hashtags = []
    if analysis["face_count"] > 0:
        hashtags += ["#portrait", "#people"]
    else:
        hashtags += ["#photooftheday"]
    hashtags += [f"#{datetime.utcnow().year}"]

    caption = f"{filename} | " + " · ".join(parts) + "\n\n" + " ".join(hashtags)
    return caption
