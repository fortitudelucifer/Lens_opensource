const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('lensElectron', {
  shellVersion: '0.1.0',
  packagingStage: 'v1.1-placeholder'
});
