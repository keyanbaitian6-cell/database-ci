async function loadImage(dataUrl) {
  return await new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('分割画像を開けませんでした。'));
    image.src = dataUrl;
  });
}

async function waitForDownload(downloadId) {
  return await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => finish(new Error('PNG保存が60秒以内に完了しませんでした。')), 60000);
    function finish(error) {
      clearTimeout(timeout);
      chrome.downloads.onChanged.removeListener(listener);
      error ? reject(error) : resolve();
    }
    function listener(delta) {
      if (delta.id !== downloadId || !delta.state) return;
      if (delta.state.current === 'complete') finish();
      if (delta.state.current === 'interrupted') finish(new Error('PNGのダウンロードが中断されました。'));
    }
    chrome.downloads.onChanged.addListener(listener);
  });
}

async function main() {
  const jobId = new URL(location.href).searchParams.get('job');
  const storageKey = `captureJob-${jobId}`;
  const stored = await chrome.storage.local.get(storageKey);
  const job = stored[storageKey];
  if (!job?.captures?.length) throw new Error('撮影データがありません。');

  const images = [];
  for (const capture of job.captures) {
    images.push({...capture, image: await loadImage(capture.dataUrl)});
  }
  const ratio = images[0].image.naturalHeight / job.viewportHeight;
  const canvas = document.createElement('canvas');
  canvas.width = images[0].image.naturalWidth;
  canvas.height = Math.ceil(job.totalHeight * ratio);
  const context = canvas.getContext('2d', {alpha: false});
  context.fillStyle = '#ffffff';
  context.fillRect(0, 0, canvas.width, canvas.height);

  for (const capture of images) {
    const destinationY = Math.round(capture.y * ratio);
    const remaining = Math.max(0, job.totalHeight - capture.y);
    const sourceHeight = Math.min(capture.image.naturalHeight, Math.ceil(remaining * ratio));
    context.drawImage(capture.image, 0, 0, capture.image.naturalWidth, sourceHeight,
      0, destinationY, capture.image.naturalWidth, sourceHeight);
  }

  const blob = await new Promise((resolve, reject) =>
    canvas.toBlob((value) => value ? resolve(value) : reject(new Error('PNGを作成できませんでした。')), 'image/png'));
  const blobUrl = URL.createObjectURL(blob);
  try {
    const downloadId = await chrome.downloads.download({
      url: blobUrl,
      filename: `database/${job.filename}`,
      conflictAction: 'uniquify',
      saveAs: false,
    });
    await waitForDownload(downloadId);
  } finally {
    URL.revokeObjectURL(blobUrl);
    await chrome.storage.local.remove(storageKey);
    const tab = await chrome.tabs.getCurrent();
    if (tab?.id) await chrome.tabs.remove(tab.id);
  }
}

main().catch((error) => {
  document.body.textContent = '保存に失敗しました：' + (error.message || error);
  console.error(error);
});
