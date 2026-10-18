#!/bin/sh
# Throwaway: install the spike plugin twice into the Windows MuseScore plugin folder:
# as a dialog plugin on 8731, and as a macro (no pluginType, so no dialog) on 8732.
set -e
here=$(dirname "$0")
dst=/mnt/c/Users/Vedat/Documents/MuseScore4/Plugins
mkdir -p "$dst/reflets-bridge-hello" "$dst/reflets-bridge-macro"
cp "$here/reflets-bridge-hello.qml" "$dst/reflets-bridge-hello/"
sed -e '/pluginType: "dialog"/d' \
    -e 's/title: "Reflets Bridge Hello"/title: "Reflets Bridge Macro"/' \
    -e 's/property int port: 8731/property int port: 8732/' \
    "$here/reflets-bridge-hello.qml" > "$dst/reflets-bridge-macro/reflets-bridge-macro.qml"
grep -H 'title:\|pluginType\|property int port\|version:' "$dst"/reflets-bridge-*/*.qml
