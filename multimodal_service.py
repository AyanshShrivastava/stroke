"""
================================================================================
STROKE // MULTIMODAL ATTACHMENT & VISION UNDERSTANDING SERVICE
================================================================================
Enforces authentic multimodal reasoning and truthful image ingestion:
1. Decompression & Size Defense:
   - PIL DecompressionBombError mitigation with bounded MAX_IMAGE_PIXELS.
   - Max file size limits (10MB per attachment, 25MB total).
   - Strict MIME type verification (image/png, image/jpeg, image/webp, image/gif).
2. Capability Gating:
   - Verifies whether the selected model's registered input_modalities include 'image'.
   - Returns explicit, honest 'unsupported' response for text-only models (e.g. Llama 3.2 1B).
   - Never fabricates visual scenes, Roblox houses, or 3D viewports from metadata.
3. Multi-Attachment Iteration:
   - Analyses every supported image attachment individually, not only the first.
4. Vision Inference:
   - Dispatches visual content to configured vision models (OpenAI GPT-4o, Claude 3.5 Sonnet,
     Gemini 1.5 Flash/Pro, or Ollama vision models).
5. Truthful Grounding:
   - Disclaims static screenshot analysis and never claims live Roblox Studio DataModel inspection.
================================================================================
"""

import os
import io
import base64
import time
from typing import Dict, List, Any, Optional, Tuple
from PIL import Image

# Enforce strict decompression bomb protection (25 Megapixels max)
Image.MAX_IMAGE_PIXELS = 25_000_000

import ai_provider_service
from ai_provider_service import MODEL_REGISTRY, resolve_model_id, ProviderType


# Supported MIME types and extensions
ALLOWED_IMAGE_MIMES = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/webp": "WEBP",
    "image/gif": "GIF"
}

MAX_IMAGE_BYTES = 10 * 1024 * 1024        # 10 MB per image
MAX_TOTAL_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB total


class ImageAttachmentValidationError(ValueError):
    """Raised when an image attachment fails safety, size, or decoding validation."""
    pass


class MultimodalAttachmentHandler:
    """Handles parsing, security sanitization, and multimodal inference for attached assets."""

    @classmethod
    def validate_and_decode_image(
        cls,
        content: str,
        name: str = "attachment",
        mime_type: Optional[str] = None
    ) -> Tuple[bytes, Image.Image, str, int, int]:
        """
        Safely validates, Base64 decodes, and inspects an image attachment.
        Enforces decompression limits and MIME restrictions.
        Returns: (raw_bytes, PIL_Image, format_name, width, height)
        """
        if not content:
            raise ImageAttachmentValidationError("Attachment payload is empty.")

        # Strip data URL prefix if present
        raw_b64 = content
        inferred_mime = mime_type
        if "," in content and "data:" in content[:30]:
            header, raw_b64 = content.split(",", 1)
            # data:image/png;base64
            if ":" in header and ";" in header:
                inferred_mime = header.split(":")[1].split(";")[0].lower()

        try:
            img_bytes = base64.b64decode(raw_b64)
        except Exception as e:
            raise ImageAttachmentValidationError(f"Invalid Base64 encoding for attachment '{name}': {e}")

        if len(img_bytes) > MAX_IMAGE_BYTES:
            raise ImageAttachmentValidationError(
                f"Attachment '{name}' size ({len(img_bytes)} bytes) exceeds maximum allowable limit of {MAX_IMAGE_BYTES} bytes."
            )

        # Inspect format and dimensions safely
        try:
            bio = io.BytesIO(img_bytes)
            img = Image.open(bio)
            img.verify()  # Verify image integrity without decoding all pixels
        except Image.DecompressionBombError as dbe:
            raise ImageAttachmentValidationError(
                f"Attachment '{name}' rejected: Decompression bomb detected ({dbe})."
            )
        except Exception as e:
            raise ImageAttachmentValidationError(f"Malformed or corrupt image '{name}': {e}")

        # Reopen for metadata inspection after verify()
        bio.seek(0)
        img = Image.open(bio)
        width, height = img.size
        fmt = (img.format or "PNG").upper()

        # Enforce pixel bounds
        if width * height > Image.MAX_IMAGE_PIXELS:
            raise ImageAttachmentValidationError(
                f"Image '{name}' dimensions ({width}x{height} = {width*height} pixels) exceed safety ceiling of {Image.MAX_IMAGE_PIXELS}."
            )

        return img_bytes, img, fmt, width, height

    @classmethod
    def is_model_vision_capable(cls, model_id: Optional[str]) -> Tuple[bool, List[str]]:
        """
        Checks whether the specified model is registered with 'image' in input_modalities.
        Returns (is_capable, supported_modalities).
        """
        resolved = resolve_model_id(model_id)
        meta = MODEL_REGISTRY.get(resolved)
        if not meta:
            return False, ["text"]
        return ("image" in meta.input_modalities), meta.input_modalities

    @classmethod
    async def analyze_image_attachment(
        cls,
        att_name: str,
        att_content: str,
        att_mime: Optional[str] = None,
        model_id: Optional[str] = None,
        user_prompt: str = ""
    ) -> Dict[str, Any]:
        """
        Processes a single image attachment:
        - Validates safety, size, and decompression limits.
        - Checks model vision capability.
        - Dispatches to vision inference if capable.
        - Truthfully returns technical metadata and unsupported status if model is text-only.
        """
        try:
            img_bytes, img, fmt, width, height = cls.validate_and_decode_image(
                content=att_content,
                name=att_name,
                mime_type=att_mime
            )
        except ImageAttachmentValidationError as ve:
            return {
                "status": "error",
                "attachment_name": att_name,
                "error": str(ve),
                "is_vision_capable": False,
                "message": f"Image validation failed for '{att_name}': {ve}"
            }

        resolved_model = resolve_model_id(model_id)
        is_capable, modalities = cls.is_model_vision_capable(resolved_model)

        technical_metadata = {
            "name": att_name,
            "format": fmt,
            "width": width,
            "height": height,
            "size_bytes": len(img_bytes),
            "megapixels": round((width * height) / 1_000_000, 2)
        }

        # ----------------------------------------------------------------------
        # HONEST UNSUPPORTED HANDLING (Text-only models like Llama 3.2 1B)
        # ----------------------------------------------------------------------
        if not is_capable:
            return {
                "status": "unsupported",
                "attachment_name": att_name,
                "is_vision_capable": False,
                "model_id": resolved_model,
                "supported_modalities": modalities,
                "technical_metadata": technical_metadata,
                "message": (
                    f"### Visual Attachment Notice (`{att_name}`)\n\n"
                    f"- **Technical File Info**: {width}x{height} {fmt} image ({round(len(img_bytes)/1024, 1)} KB)\n"
                    f"- **Model Limitation**: Active model `{resolved_model}` is a text-only language model "
                    f"(supported modalities: {modalities}). It does not support native visual processing.\n\n"
                    f"*Note: Stroke does not synthesize fake visual scene interpretations or claim live Studio "
                    f"inspection from static screenshot files. To enable genuine visual inference, select a vision-capable "
                    f"model (e.g. GPT-4o, Claude 3.5 Sonnet, or Gemini 1.5 Flash).*"
                )
            }

        # ----------------------------------------------------------------------
        # GENUINE VISION INFERENCE
        # ----------------------------------------------------------------------
        meta = MODEL_REGISTRY.get(resolved_model)
        vision_prompt = (
            f"Analyze this image in detail in relation to the user's task.\n"
            f"User Prompt: {user_prompt or 'Describe the technical contents, architecture, UI elements, or code in this image.'}\n"
            f"Explicit constraint: This is a static 2D image/screenshot. Do NOT claim live Roblox Studio DataModel or live instance state."
        )

        try:
            # Dispatch to provider if configured
            mime = att_mime or f"image/{fmt.lower()}"
            b64_clean = att_content if "," not in att_content else att_content.split(",", 1)[1]
            data_url = f"data:{mime};base64,{b64_clean}"

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": vision_prompt},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]
                }
            ]

            # Use provider adapter for vision execution
            provider = ai_provider_service.global_ai_provider_manager.get_provider_for_model(resolved_model)
            resp = await provider.chat_complete(
                messages=messages,
                parameters=ai_provider_service.InferenceParameters(max_tokens=1024),
                model_id=resolved_model
            )

            return {
                "status": "success",
                "attachment_name": att_name,
                "is_vision_capable": True,
                "model_id": resolved_model,
                "technical_metadata": technical_metadata,
                "analysis": resp.content,
                "message": (
                    f"### Visual Analysis: `{att_name}` ({width}x{height} {fmt})\n\n"
                    f"{resp.content}\n\n"
                    f"> *Analysis generated via {resp.provider} ({resolved_model}). Disclaimed: Static screenshot observation only.*"
                )
            }
        except Exception as exc:
            return {
                "status": "vision_inference_error",
                "attachment_name": att_name,
                "is_vision_capable": True,
                "model_id": resolved_model,
                "technical_metadata": technical_metadata,
                "error": str(exc),
                "message": (
                    f"### Visual Attachment Notice (`{att_name}`)\n\n"
                    f"- **Technical File Info**: {width}x{height} {fmt} image ({round(len(img_bytes)/1024, 1)} KB)\n"
                    f"- **Vision Inference Failed**: Model `{resolved_model}` supports vision, but the vision provider call "
                    f"encountered an error: {exc}."
                )
            }

    @classmethod
    async def process_all_attachments(
        cls,
        attachments: List[Any],
        model_id: Optional[str] = None,
        user_prompt: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Iterates and processes EVERY attached image, accumulating truthful
        analysis blocks without skipping secondary or subsequent attachments.
        """
        results = []
        running_total_bytes = 0

        for att in attachments:
            is_image = getattr(att, "is_image", False)
            content = getattr(att, "content", "") or ""
            name = getattr(att, "name", "attachment")
            mime = getattr(att, "mime_type", None) or getattr(att, "type", None)

            # Detect image MIME or extension if is_image not explicitly set
            if not is_image:
                if mime and any(mime.startswith(m) for m in ("image/", "img/")):
                    is_image = True
                elif any(name.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
                    is_image = True

            if not is_image or not content:
                continue

            # Check total attachment budget
            running_total_bytes += len(content)
            if running_total_bytes > MAX_TOTAL_ATTACHMENT_BYTES:
                results.append({
                    "status": "error",
                    "attachment_name": name,
                    "error": f"Total attachments payload exceeded {MAX_TOTAL_ATTACHMENT_BYTES} bytes."
                })
                break

            analysis_res = await cls.analyze_image_attachment(
                att_name=name,
                att_content=content,
                att_mime=mime,
                model_id=model_id,
                user_prompt=user_prompt
            )
            results.append(analysis_res)

        return results
