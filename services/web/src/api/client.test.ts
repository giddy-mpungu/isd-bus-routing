import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getOptimizationSettings } from './client'

function respond(status: number, statusText: string, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        statusText,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  )
}

async function failure(): Promise<ApiError> {
  try {
    await getOptimizationSettings()
  } catch (err) {
    return err as ApiError
  }
  throw new Error('expected the request to fail')
}

describe('API errors', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("carry the API's own message", async () => {
    respond(409, 'Conflict', { detail: 'That bus is in the shop' })
    const err = await failure()
    expect(err).toBeInstanceOf(ApiError)
    expect([err.status, err.message]).toEqual([409, 'That bus is in the shop'])
  })

  it('explain a form the server refused, not just "Unprocessable Entity"', async () => {
    respond(422, 'Unprocessable Entity', {
      detail: [
        {
          type: 'value_error',
          loc: ['body'],
          msg: "Value error, set both the work allowed before a break and the break's length",
        },
      ],
    })
    expect((await failure()).message).toBe(
      "set both the work allowed before a break and the break's length",
    )
  })

  it('fall back to the status text without a message', async () => {
    respond(500, 'Internal Server Error', { nothing: 'here' })
    expect((await failure()).message).toBe('Internal Server Error')
  })
})
