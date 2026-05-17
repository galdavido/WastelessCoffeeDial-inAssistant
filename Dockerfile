FROM python:3.14.3-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Set Python path to include src directory
ENV PYTHONPATH=/app/src:$PYTHONPATH

# Pre-generate PWA icons at build time so the container can run read-only
RUN python - <<'PYEOF'
import os
try:
    from PIL import Image, ImageDraw
    icons_dir = 'src/web/static/icons'
    os.makedirs(icons_dir, exist_ok=True)
    bg, accent = (15, 10, 6), (200, 134, 10)
    for size in (180, 192, 512):
        path = os.path.join(icons_dir, f'icon-{size}.png')
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, size, size], radius=size // 5, fill=bg)
        pad = size // 6
        draw.ellipse([pad, pad, size - pad, size - pad], fill=accent)
        cx, cy, cw, ch = size // 2, size // 2, size // 3, int(size * 0.28)
        cx0 = cx - cw // 2
        cy0 = cy - ch // 2 + size // 20
        draw.rectangle([cx0, cy0, cx0 + cw, cy0 + ch], fill='white')
        hw = size // 12
        draw.arc([cx0 + cw - hw // 2, cy0 + ch // 4, cx0 + cw + hw, cy0 + ch - ch // 4],
                 start=-90, end=90, fill='white', width=max(2, size // 40))
        sp = size // 5
        sh = max(3, size // 40)
        draw.rectangle([sp, cy0 + ch + size // 20, size - sp, cy0 + ch + size // 20 + sh], fill='white')
        img.save(path, 'PNG')
        print(f'Generated {path}')
except Exception as e:
    print(f'Icon generation skipped: {e}')
PYEOF

# Ne futtassuk az init_db.py-t build időben, mert a DB még nem fut
# Helyette egy entrypoint script fogja kezelni

CMD ["python", "-m", "core.web_server"]
