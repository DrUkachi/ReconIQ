"use client";

import Link from "next/link";
import { useState } from "react";

type AuthMode = "login" | "signup";

export function AuthCard({ mode: initialMode = "login" }: { mode?: AuthMode }) {
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const isLogin = mode === "login";

  return (
    <div className="w-full max-w-md overflow-hidden rounded-3xl border border-slate-200 bg-white/90 shadow-[0_20px_60px_rgba(15,23,42,0.12)] backdrop-blur-sm">
      <div className="border-b border-slate-200 bg-slate-900 px-7 py-6 text-white">
        <div className="mb-3 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-400 font-bold text-slate-900">
            R
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.24em] text-slate-300">ReconIQ</p>
            <h1 className="text-2xl font-semibold">{isLogin ? "Welcome back" : "Create account"}</h1>
          </div>
        </div>
        <p className="text-sm text-slate-300">
          {isLogin
            ? "Sign in to continue reconciling your records."
            : "Join ReconIQ and streamline your bank matching workflow."}
        </p>
      </div>

      <div className="space-y-6 px-7 py-7">
        <div className="grid grid-cols-2 rounded-xl border border-slate-200 bg-slate-100 p-1">
          <button
            type="button"
            onClick={() => setMode("login")}
            className={`rounded-lg px-3 py-2 text-sm font-medium transition ${
              isLogin ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
            }`}
          >
            Login
          </button>
          <button
            type="button"
            onClick={() => setMode("signup")}
            className={`rounded-lg px-3 py-2 text-sm font-medium transition ${
              !isLogin ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
            }`}
          >
            Create account
          </button>
        </div>

        {!isLogin && (
          <div>
            <label htmlFor="name" className="mb-2 block text-sm font-medium text-slate-700">
              Full name
            </label>
            <input
              id="name"
              type="text"
              placeholder="Jane Doe"
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-3 text-sm text-slate-900 outline-none transition focus:border-cyan-500 focus:bg-white focus:ring-4 focus:ring-cyan-100"
            />
          </div>
        )}

        <div>
          <label htmlFor="email" className="mb-2 block text-sm font-medium text-slate-700">
            Email
          </label>
          <input
            id="email"
            type="email"
            placeholder="name@company.com"
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-3 text-sm text-slate-900 outline-none transition focus:border-cyan-500 focus:bg-white focus:ring-4 focus:ring-cyan-100"
          />
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <label htmlFor="password" className="text-sm font-medium text-slate-700">
              Password
            </label>
            {isLogin && (
              <Link href="#" className="text-xs font-medium text-cyan-700 hover:text-cyan-800">
                Forgot password?
              </Link>
            )}
          </div>
          <input
            id="password"
            type="password"
            placeholder={isLogin ? "Enter your password" : "Create a secure password"}
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-3 text-sm text-slate-900 outline-none transition focus:border-cyan-500 focus:bg-white focus:ring-4 focus:ring-cyan-100"
          />
        </div>

        {!isLogin && (
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
            Use at least 8 characters with a number and symbol.
          </div>
        )}

        <button
          type="submit"
          className="w-full rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 focus:outline-none focus:ring-4 focus:ring-slate-200"
        >
          {isLogin ? "Sign in" : "Create account"}
        </button>

        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-slate-200" />
          </div>
          <div className="relative flex justify-center text-xs uppercase tracking-[0.2em] text-slate-400">
            <span className="bg-white px-2">or</span>
          </div>
        </div>

        <button
          type="button"
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
        >
          <span className="text-base">G</span>
          Continue with Google
        </button>

        <p className="text-center text-sm text-slate-600">
          {isLogin ? "Need an account?" : "Already have an account?"}{" "}
          <button
            type="button"
            onClick={() => setMode(isLogin ? "signup" : "login")}
            className="font-semibold text-cyan-700 hover:text-cyan-800"
          >
            {isLogin ? "Sign up" : "Sign in"}
          </button>
        </p>
      </div>
    </div>
  );
}
