import "./styles/index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { ApiError } from "./api/client";
import { AppShell } from "./components/layout/AppShell";
import { ToastProvider } from "./components/ui/overlays";
import { RouteError } from "./features/RouteError";

// Each module is a separate chunk; the first visit downloads only the shell and the current page.
const Overview = lazy(() => import("./features/overview/OverviewPage"));
const Datasets = lazy(() => import("./features/datasets/DatasetsPage"));
const DatasetDetail = lazy(() => import("./features/datasets/DatasetDetailPage"));
const Quality = lazy(() => import("./features/quality/QualityPage"));
const Pipelines = lazy(() => import("./features/pipelines/PipelinesPage"));
const PipelineEditor = lazy(() => import("./features/pipelines/PipelineEditorPage"));
const RunPage = lazy(() => import("./features/pipelines/RunPage"));
const Explorer = lazy(() => import("./features/explorer/ExplorerPage"));
const Analytics = lazy(() => import("./features/analytics/AnalyticsPage"));
const Analyst = lazy(() => import("./features/analyst/AnalystPage"));
const Reports = lazy(() => import("./features/reports/ReportsPage"));
const NotFound = lazy(() => import("./features/NotFoundPage"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
    },
  },
});

const router = createBrowserRouter([
  {
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { path: "/", element: <Overview /> },
      { path: "/datasets", element: <Datasets /> },
      { path: "/datasets/:id", element: <DatasetDetail /> },
      { path: "/quality", element: <Quality /> },
      { path: "/pipelines", element: <Pipelines /> },
      { path: "/pipelines/new", element: <PipelineEditor /> },
      { path: "/pipelines/:id/edit", element: <PipelineEditor /> },
      { path: "/runs/:id", element: <RunPage /> },
      { path: "/explorer", element: <Explorer /> },
      { path: "/analytics", element: <Analytics /> },
      { path: "/analyst", element: <Analyst /> },
      { path: "/reports", element: <Reports /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
