import {readFileSync} from 'node:fs';

const socket = new WebSocket(process.argv[2]);
const source = readFileSync('lib/web_import_page.dart', 'utf8');
const expression = source.match(/const _extractGraphScript = r'''([\s\S]*?)'''/)[1];
socket.onopen = () => socket.send(JSON.stringify({
  id: 1,
  method: 'Runtime.evaluate',
  params: {expression, returnByValue: true},
}));
socket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.id !== 1) return;
  console.log(message.result.result.value);
  socket.close();
};
