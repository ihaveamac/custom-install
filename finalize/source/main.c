#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <3ds.h>

#include "basetik_bin.h"

#define CIFINISH_PATH "/cifinish.bin"

// 0x10
struct finish_db_header {
	u8 magic[8];
	u32 version;
	u32 title_count;
};

// 0x30
struct finish_db_entry_v1 {
	u64 title_id;
	u8 common_key_index; // unused by this program
	bool has_seed;
	u8 magic[6]; // "TITLE" and a null byte
	u8 title_key[0x10]; // unused by this program
	u8 seed[0x10];
};

// 0x20
// this one was accidential since I mixed up the order of the members in the script
//   and the finalize program, but a lot of users probably used the bad one so I need
//   to support this anyway.
struct finish_db_entry_v2 {
	u8 magic[6]; // "TITLE" and a null byte
	u64 title_id;
	bool has_seed;
	u8 padding;
	u8 seed[0x10];
} __attribute__((packed));

// 0x20
struct finish_db_entry_v3 {
	u8 magic[6]; // "TITLE" and a null byte
	bool has_seed;
	u64 title_id;
	u8 seed[0x10];
};

// 0x350
struct ticket_dumb {
	u8 unused1[0x1DC];
	u64 title_id_be;
	u8 unused2[0x16C];
} __attribute__((packed));

// the 3 versions are put into this struct
struct finish_db_entry_final {
	bool has_seed;
	u64 title_id;
	u8 seed[0x10];
};

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

int load_cifinish(char* path, struct finish_db_entry_final **entries)
{
	FILE *fp;
	struct finish_db_header header;

	struct finish_db_entry_v1 v1;
	struct finish_db_entry_v2 v2;
	struct finish_db_entry_v3 v3;

	struct finish_db_entry_final *tmp;

	int i;
	size_t read;

	printf("Reading %s...\n", path);
	fp = fopen(path, "rb");
	if (!fp)
	{
		printf("Failed to open file. Does it exist?\n");
		return -1;
	}

	fread(&header, sizeof(header), 1, fp);

	if (memcmp(header.magic, "CIFINISH", 8))
	{
		printf("CIFINISH magic not found.\n");
		goto fail;
	}

	printf("CIFINISH version: %lu\n", header.version);

	if (header.version > 3)
	{
		printf("This version of custom-install-finalize is\n");
		printf("  too old. Please update to a new release.\n");
		goto fail;
	}

	*entries = calloc(header.title_count, sizeof(struct finish_db_entry_final));
	if (!*entries) {
		printf("Couldn't allocate memory.\n");
		printf("This should never happen.\n");
		goto fail;
	}
	tmp = *entries;

	if (header.version == 1)
	{
		for (i = 0; i < header.title_count; i++)
		{
			read = fread(&v1, sizeof(v1), 1, fp);
			if (read != 1)
			{
				printf("Couldn't read a full entry.\n");
				printf("  Is the file corrupt?\n");
				goto fail;
			}

			if (memcmp(v1.magic, "TITLE", 6))
			{
				printf("Couldn't find TITLE magic for entry.\n");
				printf("  Is the file corrupt?\n");
				goto fail;
			}
			tmp[i].has_seed = v1.has_seed;
			tmp[i].title_id = v1.title_id;
			memcpy(tmp[i].seed, v1.seed, 16);
		}
	} else if (header.version == 2) {
		for (i = 0; i < header.title_count; i++)
		{
			read = fread(&v2, sizeof(v2), 1, fp);
			if (read != 1)
			{
				printf("Couldn't read a full entry.\n");
				printf("  Is the file corrupt?\n");
				goto fail;
			}

			if (memcmp(v2.magic, "TITLE", 6))
			{
				printf("Couldn't find TITLE magic for entry.\n");
				printf("  Is the file corrupt?\n");
				goto fail;
			}
			tmp[i].has_seed = v2.has_seed;
			tmp[i].title_id = v2.title_id;
			memcpy(tmp[i].seed, v2.seed, 16);
		}
	} else if (header.version == 3) {
		for (i = 0; i < header.title_count; i++)
		{
			read = fread(&v3, sizeof(v3), 1, fp);
			if (read != 1)
			{
				printf("Couldn't read a full entry.\n");
				printf("  Is the file corrupt?\n");
				goto fail;
			}

			if (memcmp(v3.magic, "TITLE", 6))
			{
				printf("Couldn't find TITLE magic for entry.\n");
				printf("  Is the file corrupt?\n");
				goto fail;
			}
			tmp[i].has_seed = v3.has_seed;
			tmp[i].title_id = v3.title_id;
			memcpy(tmp[i].seed, v3.seed, 16);
		}
	}

	fclose(fp);
	return header.title_count;

fail:
	fclose(fp);
	return -1;
}

Result check_title_exist(u64 title_id, u64 *ticket_ids, u32 ticket_ids_length,  u64 *title_ids, u32 title_ids_length)
{
	Result ret = -2;

	for (u32 i = 0; i < ticket_ids_length; i++)
	{
		if (ticket_ids[i] == title_id)
		{
			ret++;
			break;
		}
	}

	for (u32 i = 0; i < title_ids_length; i++)
	{
		if (title_ids[i] == title_id)
		{
			ret++;
			break;
		}
	}

	return ret;
}

void finalize_install(void)
{
	Result res;
	Handle ticketHandle;
	struct ticket_dumb ticket_buf;
	struct finish_db_entry_final *entries = NULL;
	int title_count;	

	u32 titles_read;
	u32 tickets_read;

	res = AM_GetTitleCount(MEDIATYPE_SD, &titles_read);

	if (R_FAILED(res))
	{
		return;
	}

	res = AM_GetTicketCount(&tickets_read);

	if (R_FAILED(res))
	{
		return;
	}

	u64 *installed_ticket_ids = malloc(sizeof(u64) * tickets_read );
	u64 *installed_title_ids  = malloc(sizeof(u64) * titles_read  );

	res = AM_GetTitleList(&titles_read, MEDIATYPE_SD, titles_read, installed_title_ids);

	if (R_FAILED(res))
	{
		goto exit;
	}

	res = AM_GetTicketList(&tickets_read, tickets_read, 0, installed_ticket_ids);

	if (R_FAILED(res))
	{
		goto exit;
	}

	title_count = load_cifinish(CIFINISH_PATH, &entries);

	if (title_count == -1)
	{
		goto exit;
	}
	else if (title_count == 0)
	{
		printf("No titles to finalize.\n");
		goto exit;
	}

	memcpy(&ticket_buf, basetik_bin, basetik_bin_size);

	Result exist_res = 0;

	for (int i = 0; i < title_count; ++i)
	{
		exist_res = check_title_exist(entries[i].title_id, installed_ticket_ids, tickets_read, installed_title_ids, titles_read);

		if (R_SUCCEEDED(exist_res))
		{
			printf("No need to finalize %016llx, skipping...\n", entries[i].title_id);
			continue;
		}

		printf("Finalizing %016llx...\n", entries[i].title_id);

		ticket_buf.title_id_be = __builtin_bswap64(entries[i].title_id);

		res = AM_InstallTicketBegin(&ticketHandle);
		if (R_FAILED(res))
		{
			printf("Failed to begin ticket install: %08lx\n", res);
			AM_InstallTicketAbort(ticketHandle);
			goto exit;
		}

		res = FSFILE_Write(ticketHandle, NULL, 0, &ticket_buf, sizeof(struct ticket_dumb), 0);
		if (R_FAILED(res))
		{
			printf("Failed to write ticket: %08lx\n", res);
			AM_InstallTicketAbort(ticketHandle);
			goto exit;
		}

		res = AM_InstallTicketFinish(ticketHandle);
		if (R_FAILED(res))
		{
			printf("Failed to finish ticket install: %08lx\n", res);
			AM_InstallTicketAbort(ticketHandle);
			goto exit;
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

	printf("Deleting %s...\n", CIFINISH_PATH);
	unlink(CIFINISH_PATH);

	exit:

	free(entries);
	free(installed_ticket_ids);
	free(installed_title_ids);
	return;
}

int main(int argc, char* argv[])
{
	amInit();
	gfxInitDefault();
	consoleInit(GFX_TOP, NULL);

	printf("custom-install-finalize v1.6\n");

	finalize_install();
	// print this at the end in case it gets pushed off the screen
	printf("\nRepository:\n");
	printf("  https://github.com/ihaveamac/custom-install\n");
	printf("\nPress START or B to exit.\n");

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
	amExit();
	return 0;
}
