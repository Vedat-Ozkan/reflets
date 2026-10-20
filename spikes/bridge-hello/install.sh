#!/bin/sh
set -e
here=$(dirname "$0")
dst=/mnt/c/Users/Vedat/Documents/MuseScore4/Plugins
rm -rf "$dst/reflets-bridge-hello"
mkdir -p "$dst/reflets-bridge-macro"
sed -e '/pluginType: "dialog"/d' \
    -e 's/title: "Reflets Bridge Hello"/title: "Reflets Bridge Macro"/' \
    -e 's/property int port: 8731/property int port: 8732/' \
    "$here/reflets-bridge-hello.qml" > "$dst/reflets-bridge-macro/reflets-bridge-macro.qml"
grep -H 'title:\|pluginType\|property int port\|version:' "$dst"/reflets-bridge-*/*.qml
