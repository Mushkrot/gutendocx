# LibreOffice with Microsoft/macOS compatible fonts
# Based on linuxserver/libreoffice (Alpine Linux)
FROM lscr.io/linuxserver/libreoffice:latest

# Install font packages available in Alpine
# Note: Alpine uses apk, not apt-get
RUN apk add --no-cache \
    # Liberation fonts (metric-compatible with MS fonts: Times, Arial, Courier)
    font-liberation \
    # Noto fonts (good Unicode coverage)
    font-noto \
    # DejaVu fonts
    font-dejavu \
    # FreeFont (includes FreeSans, FreeSerif, FreeMono)
    font-freefont \
    # Croscore fonts (Arimo, Tinos, Cousine - metric-compatible with Arial, Times, Courier)
    font-croscore \
    # Carlito (metric-compatible with Calibri)
    font-carlito

# Copy custom fonts from host
COPY fonts/ /usr/share/fonts/custom/

# Rebuild font cache
RUN fc-cache -f -v

# Note: Liberation fonts are metric-compatible with Microsoft fonts:
# - Liberation Sans = Arial
# - Liberation Serif = Times New Roman  
# - Liberation Mono = Courier New
# Custom fonts include: EB Garamond, Libre Bodoni, Dancing Script, etc.
