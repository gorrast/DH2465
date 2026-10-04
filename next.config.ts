import type { NextConfig } from 'next';

// /api/* is the FastAPI app: uvicorn on :8000 in development, the Python function api/index.py on Vercel.
const nextConfig: NextConfig = {
  rewrites: async () => [
    {
      source: '/api/:path*',
      destination: process.env.NODE_ENV === 'development' ? 'http://127.0.0.1:8000/api/:path*' : '/api/',
    },
  ],
};

export default nextConfig;
