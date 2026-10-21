import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider, Navigate } from 'react-router-dom';
import './index.css';
import App from './App.jsx';
import UploadPage from './pages/UploadPage.jsx';
import ExplorerPage from './pages/ExplorerPage.jsx';
import VerificationPage from './pages/VerificationPage.jsx';
import TamperingLabPage from './pages/TamperingLabPage.jsx';
import PlaceholderPage from './pages/PlaceholderPage.jsx';

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Navigate to="/upload" replace /> },
      { path: 'upload',      element: <UploadPage /> },
      { path: 'explorer',    element: <ExplorerPage /> },
      { path: 'verify',      element: <VerificationPage /> },
      { path: 'lab',         element: <TamperingLabPage /> },
      { path: 'experiments', element: <PlaceholderPage title="Experiments" desc="ML experiment analytics — Task B." /> },
    ],
  },
]);

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
