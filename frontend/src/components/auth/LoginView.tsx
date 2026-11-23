import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import {
  Network,
  Mail,
  Lock,
  Eye,
  EyeOff,
  ShieldCheck,
  ArrowRight,
  Sparkles,
  Users,
  CheckCircle2,
} from 'lucide-react';

export const loginSchema = z.object({
  email: z
    .string()
    .min(1, 'Analyst email is required')
    .email('Please enter a valid email address'),
  password: z
    .string()
    .min(1, 'Password is required')
    .min(8, 'Password must be at least 8 characters'),
  rememberSession: z.boolean().optional(),
});

export type LoginFormValues = z.infer<typeof loginSchema>;

interface LoginViewProps {
  onAuthenticated: (analyst?: { email: string; name?: string }) => void;
}

export const LoginView: React.FC<LoginViewProps> = ({ onAuthenticated }) => {
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      email: '',
      password: '',
      rememberSession: false,
    },
    mode: 'onBlur',
  });

  const onSubmit = (data: LoginFormValues) => {
    setIsSubmitting(true);
    // Ready for FastAPI JWT authentication endpoint integration
    setTimeout(() => {
      onAuthenticated({
        email: data.email,
        name: data.email.split('@')[0],
      });
      setIsSubmitting(false);
    }, 200);
  };

  const handleDemoLogin = () => {
    onAuthenticated({
      email: 'investigator@muletrace.internal',
      name: 'Shaili & Raj',
    });
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#1E1035] via-[#28144B] to-[#120824] flex items-center justify-center p-4 md:p-8 relative overflow-hidden antialiased">
      {/* Decorative Radial Lighting */}
      <div className="absolute -left-20 -top-20 w-96 h-96 bg-[#7C3AED]/20 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute -right-20 -bottom-20 w-96 h-96 bg-[#5B21B6]/25 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute left-1/2 top-1/3 -translate-x-1/2 w-80 h-80 bg-fuchsia-600/10 rounded-full blur-3xl pointer-events-none" />

      {/* Main Executive Card */}
      <div className="relative z-10 max-w-4xl w-full grid grid-cols-1 md:grid-cols-12 rounded-3xl overflow-hidden shadow-2xl shadow-purple-950/70 border border-purple-500/20 bg-white">
        {/* Left Branding Showcase Panel */}
        <div className="md:col-span-5 bg-gradient-to-b from-[#28144B] via-[#1E1035] to-[#150928] p-8 md:p-10 text-white flex flex-col justify-between border-b md:border-b-0 md:border-r border-purple-900/40 relative overflow-hidden">
          <div className="absolute -top-16 -right-16 w-48 h-48 bg-purple-500/15 rounded-full blur-2xl pointer-events-none" />

          {/* Top Brand Header */}
          <div className="space-y-6">
            <div className="flex items-center gap-3">
              <div className="h-11 w-11 rounded-2xl bg-gradient-to-tr from-[#7C3AED] via-[#9333EA] to-[#C084FC] flex items-center justify-center text-white shadow-lg shadow-purple-600/40 ring-1 ring-purple-300/40">
                <Network className="h-6 w-6" />
              </div>
              <div>
                <span className="text-xl font-black tracking-tight text-white block leading-tight">
                  MuleTrace
                </span>
                <span className="block text-[10px] font-bold uppercase tracking-wider text-purple-300">
                  Financial Intelligence
                </span>
              </div>
            </div>

            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-[11px] font-semibold bg-white/10 text-purple-200 border border-purple-400/20 backdrop-blur-md">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-300" />
              <span>Analyst Security Gateway</span>
            </div>

            <div className="space-y-2">
              <h2 className="text-xl font-bold tracking-tight text-white leading-snug">
                Detect &amp; Dismantle Mule Networks
              </h2>
              <p className="text-xs text-purple-200/80 leading-relaxed">
                Enterprise surveillance and multi-hop graph intelligence for financial crime investigators.
              </p>
            </div>

            {/* Feature Bullets */}
            <div className="space-y-2.5 pt-2">
              <div className="flex items-center gap-2 text-xs text-purple-100 font-medium">
                <CheckCircle2 className="h-4 w-4 text-[#C084FC] shrink-0" />
                <span>Real-time graph anomaly triangulation</span>
              </div>
              <div className="flex items-center gap-2 text-xs text-purple-100 font-medium">
                <CheckCircle2 className="h-4 w-4 text-[#C084FC] shrink-0" />
                <span>Multi-hop layering transaction detection</span>
              </div>
              <div className="flex items-center gap-2 text-xs text-purple-100 font-medium">
                <CheckCircle2 className="h-4 w-4 text-[#C084FC] shrink-0" />
                <span>Automated SAR case dossier reporting</span>
              </div>
            </div>
          </div>

          {/* Collaborator Footer */}
          <div className="pt-8 mt-6 border-t border-purple-900/40">
            <div className="flex items-center gap-2 text-xs text-purple-300/80">
              <Users className="h-4 w-4 text-purple-400" />
              <span>Collaborators: Shaili &amp; Raj</span>
            </div>
            <div className="text-[10px] text-purple-400/60 mt-0.5">
              Financial Crime Squad
            </div>
          </div>
        </div>

        {/* Right Form Card */}
        <div className="md:col-span-7 bg-white p-8 md:p-10 flex flex-col justify-center">
          <div className="max-w-sm w-full mx-auto space-y-6">
            <div>
              <h3 className="text-2xl font-black text-[#1E1B4B] tracking-tight">
                Analyst Sign In
              </h3>
              <p className="text-xs text-purple-900/60 font-medium mt-1">
                Enter your security credentials to access the intelligence console.
              </p>
            </div>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
              {/* Analyst Email Input */}
              <div className="space-y-1.5">
                <label
                  htmlFor="email"
                  className="block text-xs font-bold text-[#1E1B4B] uppercase tracking-wider"
                >
                  Analyst Email
                </label>
                <div className="relative">
                  <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-purple-900/40" />
                  <input
                    id="email"
                    type="email"
                    autoComplete="email"
                    placeholder="analyst@muletrace.internal"
                    {...register('email')}
                    className={`w-full pl-10 pr-4 py-2.5 text-xs rounded-xl border ${
                      errors.email
                        ? 'border-rose-400 bg-rose-50/40 text-rose-900 focus:ring-rose-400/30'
                        : 'border-purple-200/80 bg-purple-50/40 text-[#1E1B4B] focus:border-[#7C3AED] focus:ring-[#7C3AED]/30'
                    } placeholder:text-purple-900/40 focus:outline-none focus:ring-2 focus:bg-white transition`}
                  />
                </div>
                {errors.email && (
                  <p role="alert" className="text-[11px] font-semibold text-rose-600 mt-1">
                    {errors.email.message}
                  </p>
                )}
              </div>

              {/* Password Input */}
              <div className="space-y-1.5">
                <label
                  htmlFor="password"
                  className="block text-xs font-bold text-[#1E1B4B] uppercase tracking-wider"
                >
                  Password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-purple-900/40" />
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="current-password"
                    placeholder="••••••••••••"
                    {...register('password')}
                    className={`w-full pl-10 pr-10 py-2.5 text-xs rounded-xl border ${
                      errors.password
                        ? 'border-rose-400 bg-rose-50/40 text-rose-900 focus:ring-rose-400/30'
                        : 'border-purple-200/80 bg-purple-50/40 text-[#1E1B4B] focus:border-[#7C3AED] focus:ring-[#7C3AED]/30'
                    } placeholder:text-purple-900/40 focus:outline-none focus:ring-2 focus:bg-white transition`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((prev) => !prev)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-purple-900/40 hover:text-purple-900 focus:outline-none"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
                {errors.password && (
                  <p role="alert" className="text-[11px] font-semibold text-rose-600 mt-1">
                    {errors.password.message}
                  </p>
                )}
              </div>

              {/* Remember Session & Forgot Link */}
              <div className="flex items-center justify-between text-xs pt-0.5">
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    {...register('rememberSession')}
                    className="rounded border-purple-300 text-[#7C3AED] focus:ring-[#7C3AED]/30 h-4 w-4 accent-[#7C3AED]"
                  />
                  <span className="text-purple-900/80 font-medium">Remember session</span>
                </label>
                <span className="text-xs text-[#7C3AED] hover:underline cursor-pointer font-semibold">
                  Forgot credentials?
                </span>
              </div>

              {/* Standard Sign In Button */}
              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full mt-2 py-2.5 px-4 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-[#6D28D9] to-[#7C3AED] hover:from-[#5B21B6] hover:to-[#6D28D9] shadow-lg shadow-purple-600/30 transition-all hover:scale-[1.01] active:scale-[0.99] disabled:opacity-50 flex items-center justify-center gap-2"
              >
                <span>{isSubmitting ? 'Authenticating...' : 'Sign In'}</span>
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </form>

            {/* Quick Demo Preview Button */}
            <div className="pt-2 border-t border-purple-100">
              <button
                type="button"
                onClick={handleDemoLogin}
                className="w-full py-2.5 px-4 rounded-xl border border-purple-200/90 text-[#6D28D9] bg-[#FAF8FF] hover:bg-purple-100/70 font-bold text-xs flex items-center justify-center gap-2 transition hover:shadow-sm"
              >
                <Sparkles className="h-3.5 w-3.5 text-[#7C3AED]" />
                <span>Preview Investigator Workspace (Demo Session)</span>
              </button>
              <p className="text-[10px] text-center text-purple-900/50 mt-2 font-medium">
                FastAPI JWT authentication ready &bull; Zero external credentials required
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
