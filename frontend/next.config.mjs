/** @type {import('next').NextConfig} */
const INTERNAL_API = process.env.INTERNAL_API_URL || "http://127.0.0.1:8000";

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // 允许用环境变量换输出目录：某些受限环境里 next build 无法删除默认的 .next
  // （实测：沙箱的 safe-delete 钩子会拦住 recursiveDelete ⇒ 构建表现成"卡死/失败"）
  distDir: process.env.NEXT_DIST_DIR || ".next",
  experimental: {
    // ★受限环境的关键开关：Next 14 默认把 webpack 编译丢给 jest-worker 子进程，
    //   子进程通过命名管道回传 stdout/stderr；沙箱禁止管道 ⇒ spawn EPERM，
    //   表现成"构建一开始就失败"。关掉后在同一进程里编译（慢一点，但能过）。
    webpackBuildWorker: false,
    // 类型检查仍会起一个 worker；用 worker_threads 而不是 fork，
    // 避开"子进程管道被沙箱拦截"的同类问题。
    workerThreads: true,
  },
  // ★单容器部署（HF Spaces）：前端与后端同源，浏览器只访问一个端口。
  //   构建期把 NEXT_PUBLIC_API_URL 设为空串，前端就发相对路径请求，
  //   由这里的 rewrite 转发到同容器内的 uvicorn。docker compose 双容器时
  //   NEXT_PUBLIC_API_URL 仍是绝对地址，这些 rewrite 不会被用到。
  async rewrites() {
    return [
      { source: "/health", destination: `${INTERNAL_API}/health` },
      { source: "/api/:path*", destination: `${INTERNAL_API}/api/:path*` },
      { source: "/docs", destination: `${INTERNAL_API}/docs` },
      { source: "/openapi.json", destination: `${INTERNAL_API}/openapi.json` },
    ];
  },
};

export default nextConfig;
