import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { getMe, hasAuthSession, login, logout, signup } from "../api/auth";
import type { SignupPayload, User } from "../api/auth";
import { AUTH_EXPIRED_EVENT } from "../api/client";

type AuthContextValue = {
  user: User | null;
  isBootstrapping: boolean;
  isAuthenticated: boolean;
  loginWithStudentId: (studentId: string, password: string, rememberLogin?: boolean) => Promise<User>;
  signupWithEmail: (payload: SignupPayload) => Promise<User>;
  refreshUser: () => Promise<User>;
  logoutUser: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isBootstrapping, setIsBootstrapping] = useState(true);

  useEffect(() => {
    if (!hasAuthSession()) {
      setIsBootstrapping(false);
      return;
    }

    getMe()
      .then(setUser)
      .catch(() => logout())
      .finally(() => setIsBootstrapping(false));
  }, []);

  useEffect(() => {
    function handleAuthExpired() {
      logout();
      setUser(null);
    }

    window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isBootstrapping,
      isAuthenticated: Boolean(user),
      async loginWithStudentId(studentId, password, rememberLogin = false) {
        try {
          await login(studentId, password, rememberLogin);
          const nextUser = await getMe();
          setUser(nextUser);
          return nextUser;
        } catch (error) {
          logout();
          setUser(null);
          throw error;
        }
      },
      async signupWithEmail(payload) {
        return signup(payload);
      },
      async refreshUser() {
        const nextUser = await getMe();
        setUser(nextUser);
        return nextUser;
      },
      logoutUser() {
        logout();
        setUser(null);
      },
    }),
    [isBootstrapping, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
