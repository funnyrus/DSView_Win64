#!/bin/bash
# make-portable.sh -- assemble a standalone Windows package of DSView
#
# Usage (from a MSYS2 MINGW64 shell, or Git Bash with MSYS2 installed):
#   ./make-portable.sh          package the current build.dir output
#   ./make-portable.sh --build  rebuild first (cmake --build build --parallel)
#   ./make-portable.sh --zip    additionally create DSView-portable.zip
#
# The result is DSView-portable/ : a folder you can copy to any Windows
# x64 machine and run DSView.exe from, without MSYS2 or Qt installed.
#
# Layout produced:
#   DSView-portable/
#     DSView.exe              application
#     res/ decoders/ demo/ lang/ NEWS25 NEWS31   runtime data (copied by the build)
#     Qt6*.dll, platforms/, imageformats/, ...    Qt runtime (windeployqt)
#     *.dll                   glib/libusb/fftw/python/... runtime (dependency scan)
#     python-home/lib/pythonX.Y   Python stdlib for the embedded decoder engine,
#                               found automatically at startup by appcontrol.cpp

set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$REPO_ROOT/build.dir"
PORTABLE="$REPO_ROOT/DSView-portable"

DO_BUILD=0
DO_ZIP=0
for arg in "$@"; do
    case "$arg" in
        --build) DO_BUILD=1 ;;
        --zip)   DO_ZIP=1 ;;
        *) echo "unknown option: $arg"; exit 1 ;;
    esac
done

#--- locate the MSYS2 mingw64 environment -------------------------------
MINGW=""
if command -v objdump.exe >/dev/null 2>&1 && command -v windeployqt6.exe >/dev/null 2>&1; then
    MINGW="$(dirname "$(command -v objdump.exe)")"
else
    for drive in c d e f g h i j; do
        if [ -d "/$drive/msys64/mingw64/bin" ]; then
            MINGW="/$drive/msys64/mingw64/bin"
            break
        fi
    done
fi
if [ -z "$MINGW" ]; then
    echo "ERROR: MSYS2 mingw64 not found. Open the 'MSYS2 MINGW64' shell and retry."
    exit 1
fi
export PATH="$MINGW:$PATH"
echo "Using toolchain: $MINGW"

#--- optionally rebuild ---------------------------------------------------
if [ "$DO_BUILD" = 1 ]; then
    if [ ! -f "$BUILD_DIR/build.ninja" ]; then
        cmake -S "$REPO_ROOT" -B "$BUILD_DIR" -G Ninja -DCMAKE_BUILD_TYPE=Release
    fi
    cmake --build "$BUILD_DIR" --parallel
fi

if [ ! -f "$BUILD_DIR/DSView.exe" ]; then
    echo "ERROR: $BUILD_DIR/DSView.exe not found. Run with --build first."
    exit 1
fi

#--- 1. fresh package directory with the application and its data --------
echo "== Creating $PORTABLE"
rm -rf "$PORTABLE"
mkdir -p "$PORTABLE"
cp "$BUILD_DIR/DSView.exe" "$PORTABLE/"
for d in res decoders demo lang; do
    cp -r "$BUILD_DIR/$d" "$PORTABLE/"
done
cp "$BUILD_DIR/NEWS25" "$BUILD_DIR/NEWS31" "$PORTABLE/"

#--- 2. Qt runtime --------------------------------------------------------
echo "== Deploying Qt runtime"
windeployqt6 --release --no-translations "$PORTABLE/DSView.exe" >/dev/null

#--- 3. non-Qt runtime DLLs (recursive dependency scan) -------------------
SYSTEM32="$(cygpath -u "$WINDIR" 2>/dev/null)/System32"
[ -d "$SYSTEM32" ] || SYSTEM32="/c/Windows/System32"

echo "== Scanning DLL dependencies"
SEEN=";"
copy_deps() {
    local file="$1" dll dep
    for dll in $(objdump -p "$file" 2>/dev/null | sed -n 's/.*DLL Name: //p'); do
        case ";$SEEN;" in *";$dll;"*) continue ;; esac
        SEEN="$SEEN$dll;"
        if [ -f "$PORTABLE/$dll" ]; then
            copy_deps "$PORTABLE/$dll"
            continue
        fi
        # system DLLs ship with Windows, everything else comes from mingw64
        if [ ! -f "$SYSTEM32/$dll" ] && [ -f "$MINGW/$dll" ]; then
            cp "$MINGW/$dll" "$PORTABLE/"
            echo "  copied $dll"
            copy_deps "$PORTABLE/$dll"
        fi
    done
}
while IFS= read -r -d '' file; do
    copy_deps "$file"
done < <(find "$PORTABLE" -name "*.dll" -print0)
copy_deps "$PORTABLE/DSView.exe"

#--- 4. Python standard library for the embedded decoder engine ----------
PY_DIR="$(ls -d "$MINGW/../lib/python3."* 2>/dev/null | sort | tail -1)"
if [ ! -d "$PY_DIR" ]; then
    echo "ERROR: cannot find the Python stdlib directory under $MINGW/../lib"
    exit 1
fi
PY_VER="$(basename "$PY_DIR")"

echo "== Packing Python stdlib (python-home/lib/$PY_VER)"
mkdir -p "$PORTABLE/python-home/lib"
cp -r "$PY_DIR" "$PORTABLE/python-home/lib/"
# drop components a headless decoder engine never uses
rm -rf "$PORTABLE/python-home/lib/$PY_VER"/{test,tkinter,idlelib,turtledemo,lib2to3,ensurepip,site-packages,__pycache__,config-$PY_VER}

#--- 5. summary -----------------------------------------------------------
SIZE="$(du -sh "$PORTABLE" | cut -f1)"
echo "== Done: $PORTABLE ($SIZE)"

if [ "$DO_ZIP" = 1 ]; then
    ZIP="$REPO_ROOT/DSView-portable.zip"
    rm -f "$ZIP"
    echo "== Creating $(basename "$ZIP")"
    powershell.exe -NoProfile -Command \
        "Compress-Archive -Path '$(cygpath -w "$PORTABLE")\*' -DestinationPath '$(cygpath -w "$ZIP")' -Force" \
        >/dev/null
    echo "   $(basename "$ZIP") ($(du -sh "$ZIP" | cut -f1))"
fi

cat <<'NOTE'

Notes:
- Run DSView.exe directly from the folder; no MSYS2/Qt/Python needed.
- To use DSLogic/DSCope hardware on the target machine, bind the WinUSB
  driver to the device once (Zadig, or the official DSView installer).
- python-home/ is located automatically at startup (see appcontrol.cpp);
  do not rename it.
NOTE
