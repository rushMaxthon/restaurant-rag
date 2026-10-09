"""Rider self sign-up: rules, phone codes, document storage and the application.

Split by responsibility: `rules` is pure (and mirrored in the rider app),
`phone` and `storage` talk to the outside world, `applications` is the state
machine that ties them together.
"""
