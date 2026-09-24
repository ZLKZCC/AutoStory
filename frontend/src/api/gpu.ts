import { http } from "./client";

export interface GpuGateStatus {
  budget_gb: number | null;
  unlimited: boolean;
  committed_gb: number;
  transient: number;
  waiting: number;
  max_concurrent: number;
}

export const getGpuStatus = () => http.get<{ data: GpuGateStatus }>("/autostory/gpu/status");
