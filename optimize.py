import os
import glob
from PIL import Image

def optimize_images():
    image_paths = glob.glob('assets/*.jpg') + glob.glob('assets/*.png') + glob.glob('assets/*.jpeg')
    for path in image_paths:
        try:
            with Image.open(path) as img:
                # Convert to RGB to safely save as WebP
                img = img.convert('RGB')
                
                # Resize if width > 1200px
                if img.width > 1200:
                    ratio = 1200.0 / img.width
                    new_height = int(img.height * ratio)
                    img = img.resize((1200, new_height), Image.Resampling.LANCZOS)
                
                # Save as WebP
                new_path = os.path.splitext(path)[0] + '.webp'
                img.save(new_path, 'webp', quality=80, optimize=True)
                print(f'Optimized: {path} -> {new_path}')
            
            # Delete original
            os.remove(path)
        except Exception as e:
            print(f'Error processing {path}: {e}')

if __name__ == '__main__':
    optimize_images()
