package com.shipmentplanner.exception;

import graphql.ErrorClassification;
import graphql.GraphQLError;

import java.util.Map;

/**
 * Thrown by service methods for expected business failures (not-found, validation, etc.).
 * Caught by {@link GraphQLExceptionResolver} and surfaced as a structured GraphQL error
 * instead of the generic INTERNAL_ERROR classification.
 *
 * <p>Example response shape when thrown from a resolver:
 * <pre>
 * {
 *   "data": { "carrier": null },
 *   "errors": [{
 *     "message": "Carrier not found: SRC",
 *     "extensions": { "classification": "NOT_FOUND" }
 *   }]
 * }
 * </pre>
 */
public class BusinessException extends RuntimeException {

    /**
     * Business error classification — also implements {@link ErrorClassification} so
     * graphql-java can embed it directly into a {@link GraphQLError}.
     */
    public enum ErrorType implements ErrorClassification {
        NOT_FOUND,
        VALIDATION_ERROR,
        BAD_REQUEST,
        CONFLICT;

        @Override
        public Object toSpecification(GraphQLError error) {
            return Map.of("classification", this.name());
        }
    }

    private final ErrorType errorType;

    public BusinessException(ErrorType errorType, String message) {
        super(message);
        this.errorType = errorType;
    }

    public ErrorType getErrorType() {
        return errorType;
    }
}
