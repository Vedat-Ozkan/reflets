import QtQuick 2.15
import MuseScore 3.0

MuseScore {
    title: "Reflets Multiwindow Spike"
    description: "Spike: first free port from 8751, own port by a nonce probe, window activity"
    version: "0.0.1"
    requiresScore: false

    readonly property var ports: [8751, 8752, 8753, 8754, 8755]
    property string nonce: ""
    property int myPort: 0
    property var probes: ({})
    property string appState: ""
    property double lastActive: 0
    property int stateChanges: 0

    Connections {
        target: Qt.application
        function onStateChanged() {
            noteState()
            stateChanges++
        }
    }

    function noteState() {
        appState = String(Qt.application.state)
        if (Qt.application.state === Qt.ApplicationActive)
            lastActive = Date.now()
    }

    function status() {
        return "port=" + myPort + " title=" + (curScore ? curScore.scoreName.replace(/ /g, "_") : "-")
            + " state=" + appState + " lastActive=" + lastActive + " changes=" + stateChanges
            + " probes=" + JSON.stringify(probes)
    }

    function onClient(clientId) {
        api.websocketserver.onMessage(clientId, function(text) {
            var words = String(text).split(" ")
            if (words[0] === "probe")
                api.websocketserver.send(clientId, "probe " + (words[1] === nonce ? "mine" : "other"))
            else
                api.websocketserver.send(clientId, words[0] + " ok " + status())
        })
    }

    function probe(port) {
        probes[port] = "no answer"
        api.websocket.open(port, function(socketId) {
            api.websocket.onMessage(socketId, function(text) {
                probes[port] = String(text)
                if (text === "probe mine")
                    myPort = port
                api.log.info("reflets-multiwindow-spike: " + status())
                api.websocket.close(socketId)
            })
            api.websocket.send(socketId, "probe " + nonce)
        })
    }

    onRun: {
        nonce = String(Math.random()).substring(2)
        noteState()
        for (var i = 0; i < ports.length; i++)
            api.websocketserver.listen(ports[i], onClient)
        for (var j = 0; j < ports.length; j++)
            probe(ports[j])
        api.log.info("reflets-multiwindow-spike: started, nonce " + nonce + ", " + status())
    }
}
