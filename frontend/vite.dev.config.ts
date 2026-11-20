import InventreeHmrPlugin from '@inventreedb/ui/vite';
import react from '@vitejs/plugin-react-swc';
import { defineConfig } from 'vite';
import { viteExternalsPlugin } from 'vite-plugin-externals';
import viteConfig, { externalLibs } from './vite.config';

/**
 * Development config - live-reload the plugin against a running InvenTree
 * development server. See the README for the matching 'plugin_dev' config.
 */
export default defineConfig(() => {
  const config: any = {
    ...viteConfig,
    resolve: {},
    server: {
      port: 5174,
      strictPort: true,
      cors: {
        preflightContinue: true,
        origin: '*'
      }
    }
  };

  delete config.esbuild;
  delete config.optimizeDeps;

  config.plugins = [
    react({
      reactRefreshHost: 'http://localhost:5173'
    }),
    viteExternalsPlugin(externalLibs),
    InventreeHmrPlugin()
  ];

  return config;
});
