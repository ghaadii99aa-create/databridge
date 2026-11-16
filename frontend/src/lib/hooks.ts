import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import { api } from "@/api/endpoints";
import { useToast } from "@/components/ui/overlays";

export function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : "Unexpected error";
}

export function useLoadSample() {
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: api.datasets.loadSample,
    onSuccess: (ds) => {
      qc.invalidateQueries();
      toast("success", `Loaded "${ds.name}" — ${ds.row_count.toLocaleString()} rows`);
      navigate(`/datasets/${ds.id}`);
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
}
