interface CheckAuthAndRedirectOptions {
  isAuthenticated: boolean;
  redirectPath: string;
  onNavigate: (path: string) => void;
  pushToast: (title: string, description: string, tone?: 'info' | 'success' | 'error') => void;
  setPendingAuthRedirectPath: (path: string | null) => void;
}

export function checkAuthAndRedirect({
  isAuthenticated,
  redirectPath,
  onNavigate,
  pushToast,
  setPendingAuthRedirectPath,
}: CheckAuthAndRedirectOptions): boolean {
  if (isAuthenticated) {
    return true;
  }

  setPendingAuthRedirectPath(redirectPath);
  pushToast('Login required', 'Please login to continue', 'info');
  onNavigate('/auth/login');
  return false;
}
