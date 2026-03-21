import os
import io
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from config import BANNER_W, BANNER_H
from anilist_api import season_tag, get_studio

def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        f"C:/Windows/Fonts/{'arialbd' if bold else 'arial'}.ttf",
        f"C:/Windows/Fonts/{'calibrib' if bold else 'calibri'}.ttf",
        f"C:/Windows/Fonts/{'verdanab' if bold else 'verdana'}.ttf",
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/liberation/LiberationSans{'-Bold' if bold else '-Regular'}.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

def generate_banner(media: dict, cover_bytes: bytes) -> bytes:
    W, H  = BANNER_W, BANNER_H
    cover = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
    bg    = cover.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(30))
    banner = bg.convert("RGBA")
    banner.alpha_composite(Image.new("RGBA", (W, H), (10, 10, 20, 200)))

    cover_h = H
    cover_w = int(cover_h * cover.width / cover.height)
    cover_x = W - cover_w
    banner.paste(cover.resize((cover_w, cover_h), Image.LANCZOS), (cover_x, 0))

    # Gradient: Transition from the dark overlay into the clear cover image
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd   = ImageDraw.Draw(grad)
    for x in range(W):
        if x < cover_x - 120:
            alpha = int(255 * 0.85) # Fully dark overlay for the background text area
        elif x < cover_x:
            # Fade out the overlay just before the cover image start
            alpha = int(255 * 0.85 * (1 - (x - (cover_x - 120)) / 120))
        else:
            alpha = 0 # Keep the sharp cover image clear
        gd.line([(x, 0), (x, H)], fill=(10, 10, 20, alpha))
    
    banner.alpha_composite(grad)
    banner = banner.convert("RGB")

    draw       = ImageDraw.Draw(banner)
    PAD        = 60
    text_max_w = cover_x - PAD - 20

    draw.text((PAD, PAD), season_tag(media), font=load_font(30), fill=(210, 210, 210))

    font_title = load_font(86, bold=True)
    title_en   = media["title"].get("english") or media["title"].get("romaji") or "Unknown"

    def wrap_text(text, font, max_w):
        words = text.split()
        lines, line = [], ""
        for w in words:
            test = (line + " " + w).strip()
            if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
                line = test
            else:
                if line:
                    lines.append(line)
                line = w
        if line:
            lines.append(line)
        return "\n".join(lines)

    wrapped = wrap_text(title_en, font_title, text_max_w)
    draw.multiline_text((PAD, PAD + 52), wrapped, font=font_title,
                        fill=(255, 255, 255), spacing=4)
    tb           = draw.multiline_textbbox((PAD, PAD + 52), wrapped, font=font_title, spacing=4)
    title_bottom = tb[3] + 16

    studio = get_studio(media)
    if studio:
        draw.text((PAD, title_bottom), studio, font=load_font(32), fill=(90, 150, 255))
        title_bottom += 48

    font_genre = load_font(26)
    gx, gy = PAD, H - 88
    for genre in (media.get("genres") or [])[0:5]: # pyre-ignore
        bbox = draw.textbbox((0, 0), genre, font=font_genre)
        tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
        
        # Calculate box dimensions with padding
        padding_x = 20
        padding_y = 12
        box_w = tw + (padding_x * 2)
        box_h = th + (padding_y * 2)
        
        rx2 = int(gx + int(box_w))
        if rx2 > text_max_w + PAD:
            break
            
        # Draw rounded rectangle for tag
        draw.rounded_rectangle([gx, gy - padding_y, rx2, gy + th + padding_y], radius=22,
                                outline=(190, 190, 190), width=2)
                                
        # Draw centered text using anchor="mm"
        # mm stands for "Middle in X" and "Middle in Y"
        center_x: float = float(gx) + (float(box_w) / 2.0)
        center_y: float = float(gy) + (float(th) / 2.0)
        draw.text((center_x, center_y), genre, font=font_genre, fill=(220, 220, 220), anchor="mm")
        
        gx = int(gx + box_w + 20)

    out = io.BytesIO()
    banner.save(out, format="JPEG", quality=92)
    out.seek(0)
    return out.read()
