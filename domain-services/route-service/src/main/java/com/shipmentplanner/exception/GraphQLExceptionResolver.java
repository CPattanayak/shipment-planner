package com.shipmentplanner.exception;

import graphql.GraphQLError;
import graphql.GraphqlErrorBuilder;
import graphql.schema.DataFetchingEnvironment;
import org.springframework.graphql.execution.DataFetcherExceptionResolverAdapter;
import org.springframework.stereotype.Component;

/**
 * Converts {@link BusinessException} into a structured GraphQL error visible in the
 * {@code errors[]} array of the response, instead of the opaque INTERNAL_ERROR that
 * an unhandled RuntimeException produces.
 */
@Component
public class GraphQLExceptionResolver extends DataFetcherExceptionResolverAdapter {

    @Override
    protected GraphQLError resolveToSingleError(Throwable ex, DataFetchingEnvironment env) {
        if (ex instanceof BusinessException bex) {
            return GraphqlErrorBuilder.newError(env)
                    .message(bex.getMessage())
                    .errorType(bex.getErrorType())
                    .build();
        }
        // Let other exceptions fall through to the default INTERNAL_ERROR handler.
        return null;
    }
}
