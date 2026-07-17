import os
import glob
from PIL import Image

def generate_responsive_images():
    image_paths = glob.glob('assets/*.webp')
    
    # Filter out already generated -600 images if script is run multiple times
    image_paths = [p for p in image_paths if not p.endswith('-600.webp')]
    
    for path in image_paths:
        try:
            with Image.open(path) as img:
                # 1. Re-save original at lower quality (65) for better compression
                img.save(path, 'webp', quality=65, optimize=True)
                
                # 2. Generate 600px width version
                if img.width > 600:
                    ratio = 600.0 / img.width
                    new_height = int(img.height * ratio)
                    img_small = img.resize((600, new_height), Image.Resampling.LANCZOS)
                else:
                    img_small = img
                
                new_path = os.path.splitext(path)[0] + '-600.webp'
                img_small.save(new_path, 'webp', quality=65, optimize=True)
                print(f'Processed: {path} and created {new_path}')
        except Exception as e:
            print(f'Error processing {path}: {e}')

if __name__ == '__main__':
    generate_responsive_images()
