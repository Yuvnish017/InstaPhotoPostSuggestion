import time

from transformers import VisionEncoderDecoderModel, ViTImageProcessor, AutoTokenizer
import torch
import google.generativeai as genai
from logger import Logger
import os
import datetime
from datetime import datetime
import traceback
from utils import pil_from_bytes, read_image_bytes
from config import GOOGLE_API_KEY, GEMINI_MODEL
print(GEMINI_MODEL)

LOGGER = Logger(log_file_name="caption_generator.log")

genai.configure(api_key=GOOGLE_API_KEY)
genai_model = genai.GenerativeModel(GEMINI_MODEL)

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
    LOGGER.info("Generating image description...")
    image = pil_from_bytes(image_bytes)

    prompt = """
Describe this photograph in detail.

Focus on what is actually visible:
- main subject
- environment and setting
- foreground and background
- lighting
- colors
- spatial relationships
- notable objects
- atmosphere and visual mood
- interesting photographic characteristics

Write a natural, detailed description in 2-4 sentences.

Do not invent details that cannot reasonably be determined from the image.
Do not discuss image quality or give an aesthetic rating.
Do not write an Instagram caption.
"""

    response = genai_model.generate_content(
        [prompt, image],
    )
    LOGGER.info(f"Image description: {response.text.strip()}")
    return response.text.strip()


# def generate_vision_caption(image_bytes):
#     image = pil_from_bytes(image_bytes)
#     image = image.resize((224, 224))  # ViT-GPT2 expects 224x224 input
#     inputs = caption_processor(images=image, return_tensors="pt").pixel_values
#
#     with torch.no_grad():
#         outputs = caption_gen_model.generate(
#             inputs,
#             min_length=20,
#             max_length=50,
#             num_beams=10,
#             length_penalty=1.5,
#             no_repeat_ngram_size=2,
#             early_stopping=True
#         )

    # caption = caption_tokenizer.decode(outputs[0], skip_special_tokens=True)
    # return caption.strip()


def infer_mood(
    aesthetic,
    sharpness,
    exposure,
    composition,
    color_harmony,
    avg_sat,
    top_hue,
    season_score,
):
    """
    Infer photographic mood from image analysis features.

    Returns:
        {
            "primary": str,
            "secondary": list[str]
        }
    """

    moods = []

    # ---------------------------------------------------------
    # 1. LIGHTING / EXPOSURE
    # ---------------------------------------------------------

    if exposure < 0.25:
        moods.append(("moody", 0.9))
    elif exposure < 0.40:
        moods.append(("dark", 0.7))
    elif exposure > 0.80:
        moods.append(("bright", 0.8))
    elif exposure > 0.65:
        moods.append(("light", 0.5))

    # ---------------------------------------------------------
    # 2. WARMTH / COLOR
    # OpenCV hue: 0-179
    # ---------------------------------------------------------

    hue = top_hue

    if hue is not None:
        hue = float(hue)

        # Red / orange
        if hue <= 25 or hue >= 170:
            moods.append(("warm", 0.8))

        # Yellow / yellow-green
        elif 25 < hue <= 45:
            moods.append(("sunny", 0.7))

        # Green
        elif 45 < hue <= 85:
            moods.append(("natural", 0.8))

        # Cyan
        elif 85 < hue <= 105:
            moods.append(("cool", 0.7))

        # Blue
        elif 105 < hue <= 135:
            moods.append(("cool", 0.9))

        # Purple / magenta
        elif 135 < hue < 170:
            moods.append(("dreamy", 0.7))

    # ---------------------------------------------------------
    # 3. SATURATION
    # ---------------------------------------------------------

    sat = avg_sat / 255.0

    if sat < 0.20:
        moods.append(("muted", 0.8))

    elif sat < 0.40:
        moods.append(("soft", 0.6))

    elif sat > 0.75:
        moods.append(("vibrant", 0.9))

    elif sat > 0.55:
        moods.append(("colorful", 0.7))

    # ---------------------------------------------------------
    # 4. COLOR HARMONY
    # ---------------------------------------------------------

    if color_harmony >= 0.85:
        moods.append(("harmonious", 0.8))
        moods.append(("dreamy", 0.4))

    elif color_harmony >= 0.70:
        moods.append(("balanced", 0.5))

    # ---------------------------------------------------------
    # 5. COMPOSITION
    # ---------------------------------------------------------

    if composition >= 0.85:
        moods.append(("cinematic", 0.8))

    elif composition >= 0.70:
        moods.append(("structured", 0.5))

    # ---------------------------------------------------------
    # 6. SHARPNESS
    # ---------------------------------------------------------

    if sharpness >= 0.85:
        moods.append(("crisp", 0.6))

    elif sharpness < 0.40:
        moods.append(("soft", 0.5))

    # ---------------------------------------------------------
    # 7. SEASONAL MATCH
    # ---------------------------------------------------------

    if season_score >= 0.85:
        moods.append(("seasonal", 0.4))

    # ---------------------------------------------------------
    # 9. SPECIAL COMBINATIONS
    # ---------------------------------------------------------

    # Dark + cool → cinematic / mysterious
    if exposure < 0.40 and hue is not None and 90 <= hue <= 140:
        moods.append(("cinematic", 1.0))
        moods.append(("mysterious", 0.8))

    # Dark + warm → atmospheric
    if exposure < 0.40 and hue is not None and (
        hue <= 45 or hue >= 170
    ):
        moods.append(("atmospheric", 0.8))

    # Bright + warm → cheerful
    if exposure > 0.65 and hue is not None and (
        hue <= 45 or hue >= 170
    ):
        moods.append(("cheerful", 0.9))

    # Bright + green → fresh
    if exposure > 0.60 and hue is not None and 45 <= hue <= 85:
        moods.append(("fresh", 0.9))

    # High saturation + good harmony → vivid
    if sat > 0.65 and color_harmony >= 0.75:
        moods.append(("vivid", 0.8))

    # Low saturation + good composition → minimal
    if sat < 0.35 and composition >= 0.75:
        moods.append(("minimal", 0.8))

    # High aesthetic + high composition
    if aesthetic >= 0.80 and composition >= 0.80:
        moods.append(("refined", 0.6))

    # ---------------------------------------------------------
    # 10. RANK MOODS
    # ---------------------------------------------------------

    if not moods:
        return {
            "primary": "calm",
            "secondary": []
        }

    # Aggregate scores for duplicate moods
    mood_scores = {}

    for mood, weight in moods:
        mood_scores[mood] = mood_scores.get(mood, 0) + weight

    ranked = sorted(
        mood_scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    primary = ranked[0][0]

    secondary = [
        mood
        for mood, _ in ranked[1:4]
    ]

    return {
        "primary": primary,
        "secondary": secondary
    }
    

def build_caption_prompt(vision_caption):
    return f"""
    You are an experienced Instagram photographer and creative writer.
    
    Create an Instagram caption for a photography post based on the information below.
    
    PHOTO DESCRIPTION:
    {vision_caption}
    
    Instructions:
    - Capture the feeling and atmosphere of the photograph, not just what is literally visible.
    - Use the photo description as the factual basis. Do not invent people, places, objects, events, or details that are not supported by it.
    - Let the mood strongly influence the emotional tone and choice of words.
    - Follow the requested writing style naturally rather than forcing it.
    - Keep the caption concise but meaningful.
    - Prefer original, subtle and evocative language over generic Instagram phrases.
    - Avoid clichés such as "a picture is worth a thousand words", "lost in the moment", "chasing dreams", or similar overused expressions.
    - Do not simply describe the image like a computer vision model.
    - Do not mention "this photo", "this image", "the picture", or "the photographer".
    - Do not use emojis.
    - Do not use quotation marks around the caption.
    - Do not add explanations.
    
    Generate exactly 3 different caption options with relevant trendy max 5 hashtags for maximum reach.
    Each option should take a slightly different creative interpretation of the same photograph while remaining consistent with its mood and style.
    
    Return ONLY the 3 captions, one per line.
    """


def get_llm_response(prompt):
    LOGGER.info("Getting LLM caption..")
    LOGGER.info(f"Prompt: {prompt}")
    """Call Gemini 1.5 Flash with the constructed prompt to get caption suggestions."""
    try:
        response = genai_model.generate_content(prompt)
        return response.text.strip()
    except Exception as err:
        LOGGER.error(f"LLM generation failed: {err}")
        LOGGER.error(traceback.format_exc())
        return "Caption generation failed."


def generate_llm_caption(file_path):
    LOGGER.info(f"Generating LLM Caption for {file_path}...")
    start_time = time.time()
    image_bytes = read_image_bytes(file_path)
    vision_caption = generate_vision_caption(image_bytes)
    prompt = build_caption_prompt(vision_caption)
    llm_response = get_llm_response(prompt)
    LOGGER.info(f"Time taken: {time.time() - start_time} seconds")
    return f"""
    Captions
    ------------
    {llm_response}
    """


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
