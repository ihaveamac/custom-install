#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <3ds.h>

#include "basetik_bin.h"

#define CIFINISH_PATH "/cifinish.bin"
#define REQUIRED_VERSION 1

// 0x10
struct finish_db_header {
	u8 magic[8];
	u32 version;
	u32 title_count;
};

// 0x30
struct finish_db_entry {
	u64 title_id;
	u8 common_key_index;
	bool has_seed;
	u8 magic[6]; // "TITLE" and a null byte
	u8 title_key[0x10];
	u8 seed[0x10];
};

// 0x350
struct ticket_dumb {
	u8 unused1[0x1BF];
	u8 title_key[0x10];
	u8 unused2[0xD];
	u64 title_id_be;
	u8 unused3[0xD];
	u8 common_key_index;
	u8 unused4[0x15E];
} __attribute__((packed));

// from FBI:
// https://github.com/Steveice10/FBI/blob/6e3a28e4b674e0d7a6f234b0419c530b358957db/source/core/http.c#L440-L453
static Result FSUSER_AddSeed(u64 titleId, const void* seed) {
    u32 *cmdbuf = getThreadCommandBuffer();

    cmdbuf[0] = 0x087A0180;
    cmdbuf[1] = (u32) (titleId & 0xFFFFFFFF);
    cmdbuf[2] = (u32) (titleId >> 32);
    memcpy(&cmdbuf[3], seed, 16);

    Result ret = 0;
    if(R_FAILED(ret = svcSendSyncRequest(*fsGetSessionHandle()))) return ret;

    ret = cmdbuf[1];
    return ret;
}

void finalize_install(void)
{
	Result res;
	Handle ticketHandle;
	struct ticket_dumb ticket_buf;
	FILE *fp;

	struct finish_db_header header;
	struct finish_db_entry *entries;

	memcpy(&ticket_buf, basetik_bin, basetik_bin_size);

	printf("Reading %s...\n", CIFINISH_PATH);
	fp = fopen(CIFINISH_PATH, "rb");
	if (!fp)
	{
		puts("Failed to open file.");
		return;
	}

	fread(&header, sizeof(struct finish_db_header), 1, fp);
	
	if (memcmp(header.magic, "CIFINISH", 8))
	{
		printf("CIFINISH magic not found in %s.\n", CIFINISH_PATH);
		fclose(fp);
		return;
	}

	entries = calloc(header.title_count, sizeof(struct finish_db_entry));
	fread(entries, sizeof(struct finish_db_entry), header.title_count, fp);
	fclose(fp);

	for (int i = 0; i < header.title_count; ++i)
	{
		// this includes the null byte
		if (memcmp(entries[i].magic, "TITLE", 6))
		{
			puts("Couldn't find TITLE magic for entry, skipping.");
			continue;
		}
		printf("Finalizing %016llx...\n", entries[i].title_id);

		ticket_buf.title_id_be = __builtin_bswap64(entries[i].title_id);
		ticket_buf.common_key_index = entries[i].common_key_index;
		memcpy(ticket_buf.title_key, entries[i].title_key, 0x10);

		res = AM_InstallTicketBegin(&ticketHandle);
		if (R_FAILED(res))
		{
			printf("Failed to begin ticket install: %08lx\n", res);
			AM_InstallTicketAbort(ticketHandle);
			free(entries);
			return;
		}

		res = FSFILE_Write(ticketHandle, NULL, 0, &ticket_buf, sizeof(struct ticket_dumb), 0);
		if (R_FAILED(res))
		{
			printf("Failed to write ticket: %08lx\n", res);
			AM_InstallTicketAbort(ticketHandle);
			free(entries);
			return;
		}

		res = AM_InstallTicketFinish(ticketHandle);
		if (R_FAILED(res))
		{
			printf("Failed to finish ticket install: %08lx\n", res);
			AM_InstallTicketAbort(ticketHandle);
			free(entries);
			return;
		}

		if (entries[i].has_seed)
		{
			res = FSUSER_AddSeed(entries[i].title_id, entries[i].seed);
			if (R_FAILED(res))
			{
				printf("Failed to install seed: %08lx\n", res);
				continue;
			}
		}
	}

	free(entries);
}

int main(int argc, char* argv[])
{
	amInit();
	sdmcInit();
	gfxInitDefault();
	consoleInit(GFX_TOP, NULL);

	puts("custom-install-finalize v1.0");

	finalize_install();
	puts("\nPress START or B to exit.");

	// Main loop
	while (aptMainLoop())
	{
		gspWaitForVBlank();
		gfxSwapBuffers();
		hidScanInput();

		// Your code goes here
		u32 kDown = hidKeysDown();
		if (kDown & KEY_START || kDown & KEY_B)
			break; // break in order to return to hbmenu
	}

	gfxExit();
	sdmcExit();
	amExit();
	return 0;
}
