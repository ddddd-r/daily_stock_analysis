import type React from 'react';
import { useState } from 'react';
import { ApiErrorAlert } from '../components/common';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { ParsedApiError } from '../api/error';
import { isParsedApiError } from '../api/error';
import { useAuth } from '../hooks';
import { SettingsAlert } from '../components/settings';
import { GOOGLE_LOGIN_URL } from '../api/auth';

const GOOGLE_ERROR_MESSAGES: Record<string, string> = {
  google_state: 'Google 登录校验失败，请重试',
  google_failed: 'Google 登录失败，请重试',
  google_not_authorized: '该 Google 账号未被授权，请联系管理员开通',
  google_not_configured: '尚未配置 Google 登录',
};

const LoginPage: React.FC = () => {
  const { login, passwordSet } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const rawRedirect = searchParams.get('redirect') ?? '';
  const redirect =
    rawRedirect.startsWith('/') && !rawRedirect.startsWith('//') ? rawRedirect : '/';
  const googleError = searchParams.get('error');

  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | ParsedApiError | null>(
    googleError ? (GOOGLE_ERROR_MESSAGES[googleError] ?? 'Google 登录失败') : null
  );

  const isFirstTime = !passwordSet;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (isFirstTime && password !== passwordConfirm) {
      setError('两次输入的密码不一致');
      return;
    }
    setIsSubmitting(true);
    try {
      const result = await login(
        isFirstTime ? 'admin' : username.trim(),
        password,
        isFirstTime ? passwordConfirm : undefined
      );
      if (result.success) {
        navigate(redirect, { replace: true });
      } else {
        setError(result.error ?? '登录失败');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-base px-4">
      <div className="w-full max-w-sm rounded-2xl border border-white/8 bg-card/80 p-6 backdrop-blur-sm">
        <h1 className="mb-2 text-xl font-semibold text-white">
          {isFirstTime ? '设置初始密码' : '管理员登录'}
        </h1>
        <p className="mb-6 text-sm text-secondary-text">
          {isFirstTime
            ? '请设置管理员密码，输入两遍确认'
            : '请输入密码以继续访问'}
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          {!isFirstTime ? (
            <div>
              <label htmlFor="username" className="mb-1 block text-sm font-medium text-secondary-text">
                用户名
              </label>
              <input
                id="username"
                type="text"
                className="input-terminal"
                placeholder="输入用户名"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={isSubmitting}
                autoComplete="username"
              />
            </div>
          ) : null}

          <div>
            <label htmlFor="password" className="mb-1 block text-sm font-medium text-secondary-text">
              {isFirstTime ? '新密码' : '密码'}
            </label>
            <input
              id="password"
              type="password"
              className="input-terminal"
              placeholder={isFirstTime ? '输入新密码' : '输入密码'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isSubmitting}
              autoFocus
              autoComplete={isFirstTime ? 'new-password' : 'current-password'}
            />
          </div>

          {isFirstTime ? (
            <div>
              <label
                htmlFor="passwordConfirm"
                className="mb-1 block text-sm font-medium text-secondary-text"
              >
                确认密码
              </label>
              <input
                id="passwordConfirm"
                type="password"
                className="input-terminal"
                placeholder="再次输入密码"
                value={passwordConfirm}
                onChange={(e) => setPasswordConfirm(e.target.value)}
                disabled={isSubmitting}
                autoComplete="new-password"
              />
            </div>
          ) : null}

          {error
            ? isParsedApiError(error)
              ? <ApiErrorAlert error={error} className="!mt-3" />
              : (
                <SettingsAlert
                  title={isFirstTime ? '设置失败' : '登录失败'}
                  message={error}
                  variant="error"
                  className="!mt-3"
                />
              )
            : null}

          <button
            type="submit"
            className="btn-primary w-full"
            disabled={isSubmitting}
          >
            {isSubmitting ? (isFirstTime ? '设置中...' : '登录中...') : isFirstTime ? '设置密码' : '登录'}
          </button>
        </form>

        {!isFirstTime ? (
          <>
            <div className="my-4 flex items-center gap-3 text-xs text-secondary-text">
              <span className="h-px flex-1 bg-white/10" />
              或
              <span className="h-px flex-1 bg-white/10" />
            </div>
            <a
              href={GOOGLE_LOGIN_URL}
              className="btn-secondary flex w-full items-center justify-center gap-2"
            >
              使用 Google 登录
            </a>
          </>
        ) : null}
      </div>
    </div>
  );
};

export default LoginPage;
