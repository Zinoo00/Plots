#!/bin/sh
# Builds Plots.app (the Mac app) in the folder above this one, from main.swift, with the engine inside it
# (plots.py, the page and the Claude Code plugin), so the app works on its own wherever it is copied.
# Needs Xcode 26 or later (swiftc, actool for the Liquid Glass icon). Safe to run again.
#   sh native/build.sh            build Plots.app next to plots.py
#   sh native/build.sh --install  also copy it to ~/Applications
set -eu
here=$(cd "$(dirname "$0")" && pwd)
src=$(cd "$here/.." && pwd)
app="$src/Plots.app"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

echo "compiling…"
swiftc -O -swift-version 5 -target "$(uname -m)-apple-macos26.0" \
  -o "$work/Plots" "$here/main.swift" -framework Cocoa -framework WebKit -framework SwiftUI 2>&1 | grep -v "^$" || true
[ -x "$work/Plots" ] || { echo "err build failed"; exit 1; }

b="$work/Plots.app"
mkdir -p "$b/Contents/MacOS" "$b/Contents/Resources/engine"
mv "$work/Plots" "$b/Contents/MacOS/Plots"
sed "s#__SOURCE__#$src#" "$here/Info.plist" > "$b/Contents/Info.plist"

# the engine: CLI, server and page
cp "$src/plots.py" "$b/Contents/Resources/engine/"
cp -R "$src/app" "$b/Contents/Resources/engine/app"
[ -f "$src/README.md" ] && cp "$src/README.md" "$b/Contents/Resources/engine/"
[ -d "$src/plugin" ] && cp -R "$src/plugin" "$b/Contents/Resources/plugin"

# the icon (an Icon Composer document, compiled to the Liquid Glass icon and an .icns) and the accent colour (a
# graphite gray, so system controls don't turn blue), both in Assets.car
if ! xcrun actool "$here/AppIcon.icon" "$here/Assets.xcassets" --compile "$b/Contents/Resources" --platform macosx \
     --minimum-deployment-target 26.0 --app-icon AppIcon --accent-color AccentColor \
     --output-partial-info-plist "$work/icon.plist" --target-device mac >/dev/null 2>&1; then
  xcrun actool "$here/AppIcon.icon" --compile "$b/Contents/Resources" --platform macosx --minimum-deployment-target 26.0 \
    --app-icon AppIcon --output-partial-info-plist "$work/icon.plist" --target-device mac >/dev/null 2>&1 \
    || echo "warn: the icon was not compiled (needs Xcode 26)"
fi

# Signed ad hoc, macOS treats every build as a new app, so it asks again for folders it had allowed (Desktop…).
# With a code-signing certificate named "Plots Local" in the login keychain (Keychain Access › Certificate
# Assistant › Create a Certificate…, type Code Signing), builds keep their permissions.
ident=$(security find-identity -v -p codesigning 2>/dev/null | grep -o '"Plots Local"' | head -1 | tr -d '"')
if [ -n "$ident" ]; then
  codesign --force --sign "$ident" "$b" >/dev/null 2>&1 || codesign --force --sign - "$b" >/dev/null 2>&1
else
  codesign --force --sign - "$b" >/dev/null 2>&1 || echo "warn: ad-hoc signing failed (the app still runs)"
fi

was_running=0
if pgrep -f "$app/Contents/MacOS/Plots" >/dev/null 2>&1; then
  was_running=1
  osascript -e 'tell application id "local.plots.app" to quit' >/dev/null 2>&1 || true
  sleep 1
fi
# a server running the engine from the app being replaced stops too; the app starts the new one
if curl -s -m 1 http://127.0.0.1:4317/api/ping 2>/dev/null | grep -q "$app/Contents/Resources/engine"; then
  curl -s -m 2 -X POST -H 'X-Plots: 1' -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:4317/api/shutdown >/dev/null 2>&1 || true
  sleep 0.5
fi
rm -rf "$app"
mv "$b" "$app"
lsreg=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
$lsreg -f "$app" >/dev/null 2>&1 || true
echo "ok built $app"
if [ "${1:-}" = "--install" ]; then
  mkdir -p "$HOME/Applications"
  rm -rf "$HOME/Applications/Plots.app"
  cp -R "$app" "$HOME/Applications/Plots.app"
  $lsreg -f "$HOME/Applications/Plots.app" >/dev/null 2>&1 || true
  echo "ok installed $HOME/Applications/Plots.app"
fi
[ "$was_running" = 1 ] && open "$app" || true
