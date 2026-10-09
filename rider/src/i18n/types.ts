/** A translation must name every key of its English source - tsc says which is missing. */
export type Translations<T> = { readonly [K in keyof T]: string };
