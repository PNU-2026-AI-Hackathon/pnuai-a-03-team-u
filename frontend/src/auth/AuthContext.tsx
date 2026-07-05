import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { getMe, login, logout, signup } from "../api/auth";
import type { SignupPayload, User } from "../api/auth";
import { ACCESS_TOKEN_KEY } from "../api/client";

type AuthContextValue = {
  user: User | null;
  isBootstrapping: boolean;
  isAuthenticated: boolean;
  loginWithEmail: (email: string, password: string) => Promise<User>;
  signupWithEmail: (payload: SignupPayload) => Promise<User>;
  logoutUser: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isBootstrapping, setIsBootstrapping] = useState(true);

  useEffect(() => {
    const token = window.localStorage.getItem(ACCESS_TOKEN_KEY);
    if (!token) {
      setIsBootstrapping(false);
      return;
    }

    getMe()
      .then(setUser)
      .catch(() => logout())
      .finally(() => setIsBootstrapping(false));
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isBootstrapping,
      isAuthenticated: Boolean(user),
      async loginWithEmail(email, password) {
        await login(email, password);
        const nextUser = await getMe();
        setUser(nextUser);
        return nextUser;
      },
      async signupWithEmail(payload) {
        const createdUser = await signup(payload);
        await login(payload.email, payload.password);
        const nextUser = await getMe();
        setUser(nextUser);
        return createdUser;
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
