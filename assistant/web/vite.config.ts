import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const tunnel = process.env.ASSISTANT_TUNNEL_MODE === "1";
const tunnelHost = (process.env.ASSISTANT_TUNNEL_HOST || "").trim();
const apiPort = process.env.ASSISTANT_API_PORT || "9242";

export default defineConfig({
  plugins: [react()],
  server: {
    host: tunnel ? "127.0.0.1" : "::",
    port: Number(process.env.ASSISTANT_UI_PORT || 9241),
    strictPort: true,
    ...(tunnel
      ? {
          allowedHosts: [
            ".ngrok-free.app",
            ".ngrok-free.dev",
            ".ngrok.app",
            ".ngrok.io",
            "localhost",
            "127.0.0.1",
            ...(tunnelHost ? [tunnelHost] : []),
          ],
          hmr: false,
        }
      : {}),
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${apiPort}`,
        changeOrigin: true,
        ws: true,
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            const token = req.headers["x-assistant-lan-token"];
            const csrf = req.headers["x-assistant-csrf"];
            if (typeof token === "string") proxyReq.setHeader("x-assistant-lan-token", token);
            if (typeof csrf === "string") proxyReq.setHeader("x-assistant-csrf", csrf);
            const remote = req.socket?.remoteAddress;
            if (remote) proxyReq.setHeader("x-forwarded-for", remote);
          });
        },
      },
    },
  },
});
