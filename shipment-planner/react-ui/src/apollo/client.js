/**
 * Apollo Client pointing at the FastAPI gateway's GraphQL pass-through.
 *
 * In Docker   : nginx proxies /api/* → fastapi-gateway:8000 (no CORS needed)
 * In dev (npm run dev): vite proxies /api/* → localhost:8000
 *
 * The FastAPI endpoint forwards to Apollo Router → Spring Boot subgraphs.
 */
import { ApolloClient, InMemoryCache, HttpLink, from } from '@apollo/client';
import { onError } from '@apollo/client/link/error';

const errorLink = onError(({ graphQLErrors, networkError }) => {
  if (graphQLErrors)
    graphQLErrors.forEach(({ message, locations, path }) =>
      console.error(`[GraphQL error] ${message}`, { locations, path })
    );
  if (networkError)
    console.error('[Network error]', networkError);
});

const httpLink = new HttpLink({
  // Relative URL — works with both the Nginx proxy (Docker) and Vite dev proxy
  uri: '/api/v1/graphql',
});

export const apolloClient = new ApolloClient({
  link: from([errorLink, httpLink]),
  cache: new InMemoryCache({
    typePolicies: {
      Query: {
        fields: {
          shipments: { merge: false },  // always replace on refetch
        },
      },
    },
  }),
  defaultOptions: {
    watchQuery: { fetchPolicy: 'cache-and-network' },
  },
});
