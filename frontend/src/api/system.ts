import { request } from './client';
import { HealthResponse, ProvidersResponse, ToolsResponse } from '../types/api';

/**
 * Health check endpoint.
 * Consumes: GET /health
 */
export async function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

/**
 * Available model providers.
 * Consumes: GET /api/providers
 */
export async function getProviders(): Promise<ProvidersResponse> {
  return request<ProvidersResponse>('/api/providers');
}

/**
 * Registered workspace and agent tools.
 * Consumes: GET /api/tools
 */
export async function getTools(): Promise<ToolsResponse> {
  return request<ToolsResponse>('/api/tools');
}
