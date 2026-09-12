"use client";

import Link from "next/link";
import { useState } from "react";

type AuthMode = "login" | "signup";

export function AuthCard({ mode: initialMode = "login" }: { mode?: AuthMode }) {
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const isLogin = mode === "login";

  return (
    <div className="w-full max-w-md overflow-hidden rounded-[28px] border border-slate-200 bg-white/90 shadow-[0_24px_70px_rgba(15,23,42,0.14)] backdrop-blur-sm">
      <div className="relative overflow-hidden border-b border-slate-200 bg-[linear-gradient(135deg,_#0f172a,_#111827_42%,_#0f172a)] px-7 py-7 text-white">
        <div className="absolute -right-10 -top-10 h-28 w-28 rounded-full bg-cyan-400/20 blur-2xl" />
        <div className="absolute bottom-0 left-0 h-20 w-20 rounded-full bg-violet-500/20 blur-2xl" />

        <div className="relative">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-cyan-300 via-cyan-400 to-cyan-600 text-lg font-black text-slate-950 shadow-lg shadow-cyan-500/30">
              R
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.3em] text-slate-300">RekonIQ</p>
              <h1 className="text-2xl font-bold">{isLogin ? "Welcome back" : "Create account"}</h1>
            </div>
          </div>

          <p className="max-w-xs text-sm leading-6 text-slate-300">
            {isLogin
              ? "Access your reconciliation workspace and resolve exceptions in real time."
              : "Start matching statements, assigning exceptions, and closing the books faster."}
          </p>
        </div>
      </div>

      <div className="space-y-6 px-7 py-7">
        <div className="grid grid-cols-2 rounded-2xl border border-slate-200 bg-slate-100 p-1">
          <button
            type="button"
            onClick={() => setMode("login")}
            className={`rounded-xl px-3 py-2.5 text-sm font-semibold transition ${
              isLogin ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
            }`}
          >
            Login
          </button>
          <button
            type="button"
            onClick={() => setMode("signup")}
            className={`rounded-xl px-3 py-2.5 text-sm font-semibold transition ${
              !isLogin ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
            }`}
          >
            Sign up
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
            Work email
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
          <div className="rounded-2xl border border-cyan-100 bg-cyan-50 p-3 text-xs leading-5 text-slate-600">
            Use at least 8 characters, including a number and symbol for stronger account security.
          </div>
        )}

        <button
          type="submit"
          className="w-full rounded-xl bg-gradient-to-r from-slate-900 via-slate-800 to-cyan-700 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-cyan-500/10 transition hover:opacity-95 focus:outline-none focus:ring-4 focus:ring-cyan-200"
        >
          {isLogin ? "Sign in" : "Create account"}
        </button>

        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-slate-200" />
          </div>
          <div className="relative flex justify-center text-[10px] uppercase tracking-[0.22em] text-slate-400">
            <span className="bg-white px-2">or continue with</span>
          </div>
        </div>

        <button
          type="button"
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
        >
          <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-slate-100 text-xs font-bold text-slate-700">
            G
          </span>
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
