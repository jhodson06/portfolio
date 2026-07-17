import os
from PIL import Image, ImageDraw, ImageFont

def create_favicon():
    size = 512
    img = Image.new('RGB', (size, size), '#121314')
    draw = ImageDraw.Draw(img)
    
    # Try to load a nice font, fallback to default
    try:
        font = ImageFont.truetype('arial.ttf', 240)
    except:
        try:
            font = ImageFont.truetype('segoeui.ttf', 240)
        except:
            font = ImageFont.load_default()
    
    text = "JH"
    # Get bounding box for text
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    
    # Draw text centered
    x = (size - w) / 2
    y = (size - h) / 2 - 20
    draw.text((x, y), text, font=font, fill='#8fd7c4')
    
    # Draw a thin border
    draw.rectangle([20, 20, size-20, size-20], outline='#8fd7c4', width=12)
    
    img.save('apple-touch-icon.png')
    img.resize((32, 32), Image.Resampling.LANCZOS).save('favicon.png')
    img.resize((192, 192), Image.Resampling.LANCZOS).save('android-chrome-192x192.png')
    img.resize((512, 512), Image.Resampling.LANCZOS).save('android-chrome-512x512.png')
    
    # Create an SVG version as well
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">
  <rect width="100%" height="100%" fill="#121314"/>
  <rect x="20" y="20" width="{size-40}" height="{size-40}" fill="none" stroke="#8fd7c4" stroke-width="12"/>
  <text x="50%" y="55%" font-family="Arial, sans-serif" font-size="240" font-weight="bold" fill="#8fd7c4" text-anchor="middle" dominant-baseline="middle">JH</text>
</svg>'''
    with open('favicon.svg', 'w') as f:
        f.write(svg)

if __name__ == '__main__':
    create_favicon()
