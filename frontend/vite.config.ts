import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // Backend the dev server proxies /api to. Override with AAP_API_TARGET when
  // the API runs on another host or port, e.g. AAP_API_TARGET=http://10.0.0.5:9000
  const apiTarget = env.AAP_API_TARGET || 'http://127.0.0.1:8000';

  return {
    plugins: [react()],
    server: {
      port: Number(env.VITE_PORT) || 5173,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      chunkSizeWarningLimit: 6000,
    },
  };
});
