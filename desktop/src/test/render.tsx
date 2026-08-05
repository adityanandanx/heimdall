import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";

export function renderWithQuery(ui: React.ReactNode) {
    const client = new QueryClient({
        defaultOptions: { queries: { retry: false } },
    });
    return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}