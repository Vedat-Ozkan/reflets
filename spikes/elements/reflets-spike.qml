// Throwaway spike plugin for the element survey (research/musescore-4.7.5-element-coverage.md, "Needs a
// live spike"). Runs JavaScript sent over a WebSocket so experiments need no MuseScore restart.
// Never ship this: it runs any code a client that knows the token sends.
import QtQuick 2.15
import MuseScore 3.0
import FileIO 3.0

MuseScore {
    title: "Reflets Spike"
    description: "Element spike for Reflets development. Do not install for normal use."
    version: "0.0.1"
    requiresScore: false

    readonly property int port: 8732
    property string token: ""
    property var authed: ({})
    property var lib: ({})  // helpers a snippet stores for later snippets

    FileIO { id: tokenFile }

    function localPath(url) {
        var p = decodeURIComponent(String(url).replace(/^file:\/\//, ""))
        return /^\/[A-Za-z]:/.test(p) ? p.substring(1) : p
    }

    function evaluate(code) {
        // Snippets see curScore, newElement, cmd, fraction, Element, lib and api through this scope.
        return eval("(function(){" + code + "\n})()")
    }

    function handle(clientId, text) {
        var nl = String(text).indexOf("\n")
        var head = (nl < 0 ? String(text) : String(text).substring(0, nl)).split(" ")
        var body = nl < 0 ? "" : String(text).substring(nl + 1)
        var id = head[0]
        if (head[1] === "hello") {
            if (head[2] !== "token=" + token)
                return id + " err unauthorized"
            authed[clientId] = true
            return id + " ok mscore=" + mscoreVersion + " division=" + division
        }
        if (!authed[clientId])
            return id + " err unauthorized"
        if (head[1] === "js") {
            var result = evaluate(body)
            return id + " ok " + JSON.stringify(result === undefined ? null : result)
        }
        return id + " err bad-request"
    }

    onRun: {
        token = ""
        for (var i = 0; i < 32; i++)
            token += Math.floor(Math.random() * 16).toString(16)
        tokenFile.source = localPath(Qt.resolvedUrl("reflets-spike-token.txt"))
        tokenFile.write(token)
        api.websocketserver.listen(port, function(clientId) {
            api.websocketserver.onMessage(clientId, function(text) {
                var reply
                try {
                    reply = handle(clientId, text)
                } catch (e) {
                    reply = String(text).split(" ")[0] + " err exception " + String(e) + (e && e.stack ? " | " + e.stack : "")
                }
                api.websocketserver.send(clientId, reply)
            })
        })
        api.log.info("reflets-spike: listening on " + port)
    }
}
