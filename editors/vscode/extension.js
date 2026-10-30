const vscode = require("vscode");
const { LanguageClient } = require("vscode-languageclient/node");

let client;

function activate(context) {
  const command = vscode.workspace.getConfiguration("lnpl").get("serverPath", "lnpl");
  // No `transport`: vscode-languageclient 9.0.1 appends `--stdio` for TransportKind.stdio
  // (client/src/node/main.ts:453-454) and already uses stdio when transport is undefined (main.ts:465).
  const serverOptions = { command, args: ["lsp"] };
  const clientOptions = { documentSelector: [{ scheme: "file", language: "lnpl" }] };
  client = new LanguageClient("lnpl", "LNPL", serverOptions, clientOptions);
  client.start();
}

function deactivate() {
  return client ? client.stop() : undefined;
}

module.exports = { activate, deactivate };
