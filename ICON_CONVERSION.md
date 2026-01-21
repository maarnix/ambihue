# Icon Conversion Guide

I've created two SVG files for your Home Assistant add-on:

- **icon.svg** - Square icon (256x256) for the add-on store
- **logo.svg** - Wide logo (512x256) for the add-on detail page

## Design Elements

### Icon (icon.svg)
- Dark background (#1a1a2e)
- TV with rainbow Ambilight glow around edges
- Three Hue light bulbs below (blue, purple, orange)
- Sync arrows showing data flow
- Small sync icon in corner

### Logo (logo.svg)
- Wide format showing the complete system
- Left: TV with Ambilight effect
- Center: Connection arrows with sync icon
- Right: Hue Bridge with 4 connected light bulbs
- "AmbiHue" text with tagline

## Converting SVG to PNG

### Method 1: Online Conversion (Easiest)
1. Go to https://svgtopng.com/ or https://cloudconvert.com/svg-to-png
2. Upload `icon.svg` and convert to PNG at 256x256 pixels
3. Upload `logo.svg` and convert to PNG at 512x256 pixels
4. Download and rename:
   - `icon.svg` → `icon.png`
   - `logo.svg` → `logo.png`

### Method 2: Inkscape (Best Quality)
1. Install Inkscape: https://inkscape.org/release/
2. For icon.png:
   ```bash
   inkscape icon.svg --export-type=png --export-filename=icon.png -w 256 -h 256
   ```
3. For logo.png:
   ```bash
   inkscape logo.svg --export-type=png --export-filename=logo.png -w 512 -h 256
   ```

### Method 3: ImageMagick
```bash
convert -background none -density 300 icon.svg -resize 256x256 icon.png
convert -background none -density 300 logo.svg -resize 512x256 logo.png
```

### Method 4: Browser (Quick Preview)
1. Open the SVG files in Chrome/Firefox
2. Right-click → "Save Image As..." → Save as PNG
3. May need to resize to exact dimensions afterward

## Recommended Sizes

Home Assistant add-ons typically use:
- **icon.png**: 256x256 pixels (some use 512x512 for retina displays)
- **logo.png**: Any width x 256 height (512x256 works well)

## Optional: Create Retina Versions

For high-DPI displays, you can also create larger versions:
- **icon.png**: 512x512 pixels
- **logo.png**: 1024x512 pixels

Home Assistant will automatically scale them down as needed.

## Customization

If you want to modify the design:
1. Edit the SVG files with any text editor
2. Colors are in hex format (e.g., `#1a1a2e`)
3. Key colors used:
   - Background: `#1a1a2e` (dark navy)
   - TV Screen: `#0f3460` (dark blue)
   - Accent: `#00d9ff` (cyan)
   - Red accent: `#e94560`
   - Light colors: `#4A90E2` (blue), `#9B59B6` (purple), `#E67E22` (orange), `#F39C12` (yellow)

## Final Step

After conversion, place the PNG files in the root directory:
```
c:\Users\HA\ambihue\
├── icon.png
├── logo.png
└── (other files...)
```

Home Assistant will automatically detect and use these files when displaying your add-on in the store.
