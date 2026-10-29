import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { getDemoKey, setDemoKey, onUnauthorized, request, ApiError } from '../api/client';
import { DemoSignInModal } from '../components/auth/DemoSignInModal';
import * as systemApi from '../api/system';

describe('Demo API Authentication Frontend Security', () => {
  beforeEach(() => {
    sessionStorage.clear();
    setDemoKey(null);
    vi.restoreAllMocks();
  });

  describe('API Client Authentication Behavior', () => {
    it('initial state has no demo key', () => {
      expect(getDemoKey()).toBeNull();
    });

    it('sets and retrieves demo key from sessionStorage and memory', () => {
      setDemoKey('test-secret-key-xyz');
      expect(getDemoKey()).toBe('test-secret-key-xyz');
      expect(sessionStorage.getItem('orion_demo_key')).toBe('test-secret-key-xyz');

      setDemoKey(null);
      expect(getDemoKey()).toBeNull();
      expect(sessionStorage.getItem('orion_demo_key')).toBeNull();
    });

    it('attaches Authorization Bearer header when demo key is set', async () => {
      setDemoKey('demo-token-123');

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ status: 'ok' }),
      });
      global.fetch = mockFetch;

      await request('/api/tools');

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const callArgs = mockFetch.mock.calls[0];
      const headers = callArgs[1]?.headers as Headers;
      expect(headers.get('Authorization')).toBe('Bearer demo-token-123');
    });

    it('does not send Authorization header when demo key is absent', async () => {
      setDemoKey(null);

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ status: 'ok' }),
      });
      global.fetch = mockFetch;

      await request('/health');

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const callArgs = mockFetch.mock.calls[0];
      const headers = callArgs[1]?.headers as Headers;
      expect(headers.get('Authorization')).toBeNull();
    });

    it('handles HTTP 401 response: clears key and triggers onUnauthorized callback', async () => {
      setDemoKey('stale-or-invalid-key');

      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ detail: 'Invalid authentication credentials.' }),
      });
      global.fetch = mockFetch;

      const unauthorizedCallback = vi.fn();
      const unsubscribe = onUnauthorized(unauthorizedCallback);

      await expect(request('/api/sessions')).rejects.toThrow(ApiError);

      expect(getDemoKey()).toBeNull();
      expect(sessionStorage.getItem('orion_demo_key')).toBeNull();
      expect(unauthorizedCallback).toHaveBeenCalledTimes(1);

      unsubscribe();
    });
  });

  describe('DemoSignInModal Component', () => {
    it('renders modal with required elements, password input, and shared-key disclaimer', () => {
      render(
        <DemoSignInModal
          isOpen={true}
          onSuccess={vi.fn()}
        />
      );

      expect(screen.getByText('Orion Demo Access')).toBeInTheDocument();
      expect(screen.getByText(/Shared Demo Secret/i)).toBeInTheDocument();
      expect(screen.getByText(/does not provide individual user identities/i)).toBeInTheDocument();

      const input = screen.getByTestId('demo-key-input') as HTMLInputElement;
      expect(input).toBeInTheDocument();
      expect(input.type).toBe('password');

      const submitButton = screen.getByTestId('demo-sign-in-button');
      expect(submitButton).toBeDisabled();
    });

    it('toggles password visibility with show/hide button', () => {
      render(
        <DemoSignInModal
          isOpen={true}
          onSuccess={vi.fn()}
        />
      );

      const input = screen.getByTestId('demo-key-input') as HTMLInputElement;
      expect(input.type).toBe('password');

      const toggleButton = screen.getByTitle('Show key');
      fireEvent.click(toggleButton);
      expect(input.type).toBe('text');

      const hideButton = screen.getByTitle('Hide key');
      fireEvent.click(hideButton);
      expect(input.type).toBe('password');
    });

    it('successfully signs in with valid credentials and triggers onSuccess', async () => {
      const onSuccessMock = vi.fn();
      vi.spyOn(systemApi, 'getProviders').mockResolvedValue({
        providers: ['nebius', 'hermes'],
        default: 'nebius',
      });

      render(
        <DemoSignInModal
          isOpen={true}
          onSuccess={onSuccessMock}
        />
      );

      const input = screen.getByTestId('demo-key-input');
      const submitButton = screen.getByTestId('demo-sign-in-button');

      fireEvent.change(input, { target: { value: 'valid-test-key-123' } });
      expect(submitButton).not.toBeDisabled();

      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(onSuccessMock).toHaveBeenCalledTimes(1);
        expect(getDemoKey()).toBe('valid-test-key-123');
      });
    });

    it('rejects invalid key, clears key, and shows error message without printing key', async () => {
      const onSuccessMock = vi.fn();
      vi.spyOn(systemApi, 'getProviders').mockRejectedValue(
        new ApiError('Invalid authentication credentials.', 401)
      );

      render(
        <DemoSignInModal
          isOpen={true}
          onSuccess={onSuccessMock}
        />
      );

      const input = screen.getByTestId('demo-key-input');
      const submitButton = screen.getByTestId('demo-sign-in-button');

      fireEvent.change(input, { target: { value: 'bad-secret-key-999' } });
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(onSuccessMock).not.toHaveBeenCalled();
        expect(screen.getByTestId('demo-sign-in-error')).toHaveTextContent(
          'Invalid demo key. Please verify credentials and try again.'
        );
        expect(getDemoKey()).toBeNull();
      });

      // Confirm secret key was NOT printed into document text
      expect(screen.queryByText(/bad-secret-key-999/)).not.toBeInTheDocument();
    });
  });
});
