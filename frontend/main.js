const ASSET_VERSION = '20260614-box-tiles';
const APP_SCRIPTS = [
  'core.js',
  'ui-common.js',
  'inventory-ui.js',
  'registration-page.js',
  'inventory-page.js',
  'admin-page.js',
  'app.js',
];

function loadScript(name) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = `./${name}?v=${ASSET_VERSION}`;
    script.onload = resolve;
    script.onerror = () => reject(new Error(`脚本加载失败：${name}`));
    document.body.appendChild(script);
  });
}

async function start() {
  for (const script of APP_SCRIPTS) {
    await loadScript(script);
  }
}

void start();
