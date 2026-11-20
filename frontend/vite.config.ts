import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { viteExternalsPlugin } from 'vite-plugin-externals';

/**
 * These libraries are provided by the InvenTree core application (as globals
 * on the window object), and must not be bundled with the plugin.
 */
export const externalLibs: Record<string, string> = {
  react: 'React',
  'react-dom': 'ReactDOM',
  ReactDom: 'ReactDOM',
  '@lingui/core': 'LinguiCore',
  '@lingui/react': 'LinguiReact',
  '@mantine/core': 'MantineCore',
  '@mantine/notifications': 'MantineNotifications'
};

const externalKeys = Object.keys(externalLibs);

/**
 * Build the frontend as an ES module, into the 'static' directory of the plugin.
 */
export default defineConfig({
  plugins: [
    react({
      jsxRuntime: 'classic'
    }),
    viteExternalsPlugin(externalLibs)
  ],
  esbuild: {
    jsx: 'preserve'
  },
  build: {
    target: 'esnext',
    cssCodeSplit: false,
    manifest: true,
    // The build output is committed to git, so keep it small and reproducible
    sourcemap: false,
    rollupOptions: {
      preserveEntrySignatures: 'exports-only',
      input: ['./src/Workshop.tsx'],
      output: [
        // Un-hashed file, for backwards compatibility
        {
          dir: '../inventree_workshop/static',
          entryFileNames: '[name].js',
          assetFileNames: 'assets/[name].[ext]',
          globals: externalLibs
        },
        // Hashed file, for cache busting (preferred by InvenTree if present)
        {
          dir: '../inventree_workshop/static',
          entryFileNames: '[name]-[hash].js',
          assetFileNames: 'assets/[name].[ext]',
          globals: externalLibs
        }
      ],
      external: externalKeys
    }
  },
  optimizeDeps: {
    exclude: externalKeys
  }
});
