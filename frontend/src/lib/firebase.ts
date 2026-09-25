import { initializeApp, type FirebaseApp } from "firebase/app";
import { getAuth } from "firebase/auth";

const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

const isConfigured = Object.values(config).every(Boolean);
let app: FirebaseApp | undefined;
if (isConfigured) app = initializeApp(config);

export const firebaseConfigured = isConfigured;
export const firebaseAuth = app ? getAuth(app) : undefined;
