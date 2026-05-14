export type AuthUser = {
  id: string;
  email: string;
};

export type AuthMeResponse = AuthUser;

export type AuthCredentials = {
  email: string;
  password: string;
};

/** API error envelope per docs/API.md §Conventions. */
export type ApiErrorDetail = {
  loc?: ReadonlyArray<string>;
  msg?: string;
};

export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
    details?: ReadonlyArray<ApiErrorDetail>;
  };
};
